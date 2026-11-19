import logging
import time
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from visagassist import __version__, historial, limites
from visagassist.agente import Agente
from visagassist.claude import ErrorClaude
from visagassist.config import obtener_configuracion
from visagassist.db import obtener_sesion
from visagassist.herramientas.productos import FiltrosBusqueda, ProductoResumen, buscar_productos
from visagassist.identidad import INVITADO, Identidad, PaseInvalido, Rol, verificar_pase
from visagassist.proveedores import elegir_proveedor
from visagassist.seguridad import filtrar_respuesta, limpiar_mensaje

registro_log = logging.getLogger(__name__)

app = FastAPI(
    title="VisagAssist",
    version=__version__,
    description=(
        "Asistente con IA para la tienda VisagShop. Responde preguntas en español "
        "consultando los datos reales de la tienda mediante herramientas fijas de solo lectura.\n\n"
        "**Identidad:** sin encabezado `Authorization` se atiende como invitado (solo catálogo). "
        "Clientes y administrador llegan con un pase firmado por el servidor de VisagShop "
        "(`Authorization: Bearer <pase>`)."
    ),
)


@app.middleware("http")
async def encabezados_de_seguridad(peticion: Request, siguiente):  # type: ignore[no-untyped-def]
    respuesta: Response = await siguiente(peticion)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "no-referrer"
    if peticion.url.path.startswith(("/api/v1/chat", "/api/v1/conversaciones")):
        # Conversaciones privadas: que ningún navegador ni proxy las guarde en caché.
        respuesta.headers["Cache-Control"] = "no-store"
    return respuesta


@app.exception_handler(limites.LimiteAlcanzado)
def _limite_alcanzado(_peticion: Request, error: limites.LimiteAlcanzado) -> JSONResponse:
    return JSONResponse(
        {"detail": error.mensaje},
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        headers={"Retry-After": str(error.reintentar_en)},
    )


SesionTienda = Annotated[Session, Depends(obtener_sesion)]
SesionAsistente = Annotated[Session, Depends(historial.obtener_sesion_asistente)]


def obtener_identidad(authorization: Annotated[str | None, Header()] = None) -> Identidad:
    if not authorization:
        return INVITADO
    esquema, _, pase = authorization.partition(" ")
    secreto = obtener_configuracion().secreto_identidad
    if esquema.lower() != "bearer" or not pase or secreto is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Pase de identidad no válido")
    try:
        return verificar_pase(pase, secreto.get_secret_value())
    except PaseInvalido as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Pase de identidad no válido") from error


@lru_cache
def _agente_configurado() -> Agente | None:
    proveedor = elegir_proveedor(obtener_configuracion())
    if proveedor is None:
        return None
    registro_log.info("Proveedor de IA: %s (%s)", proveedor.nombre, proveedor.modelo)
    return Agente(proveedor.cliente, modelo=proveedor.modelo)


def obtener_agente() -> Agente:
    agente = _agente_configurado()
    if agente is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "El asistente no está configurado (falta la clave)"
        )
    return agente


def obtener_limites() -> limites.Limites:
    c = obtener_configuracion()
    return limites.Limites(
        por_hora={
            Rol.INVITADO: c.limite_hora_invitado,
            Rol.CLIENTE: c.limite_hora_cliente,
            Rol.ADMINISTRADOR: c.limite_hora_administrador,
        },
        presupuesto_diario_usd=c.presupuesto_diario_usd,
    )


Quien = Annotated[Identidad, Depends(obtener_identidad)]


def obtener_origen(peticion: Request, quien: Quien) -> str:
    secreto = obtener_configuracion().secreto_identidad
    clave = secreto.get_secret_value() if secreto else ""
    if quien.origen:
        return limites.huella_origen(f"pase:{quien.origen}", clave)
    ip = peticion.client.host if peticion.client else None
    return limites.huella_origen(ip, clave)


AgenteListo = Annotated[Agente, Depends(obtener_agente)]


class Estado(BaseModel):
    estado: str
    aplicacion: str
    version: str
    base_de_datos: str | None = None


@app.get("/api/v1/estado", tags=["Estado"], summary="Salud del servicio")
def estado() -> Estado:
    return Estado(estado="OK", aplicacion="VisagAssist", version=__version__)


@app.get("/api/v1/estado/base", tags=["Estado"], summary="Salud del servicio y de la base")
def estado_con_base(sesion: SesionTienda) -> Estado:
    try:
        sesion.execute(text("SELECT 1"))
        base = "OK"
    except Exception:  # la salud no debe romperse si la base está caída
        base = "sin conexión"
    return Estado(estado="OK", aplicacion="VisagAssist", version=__version__, base_de_datos=base)


class PeticionChat(BaseModel):
    mensaje: str = Field(min_length=1, max_length=500, examples=["¿Tienen jeans talla 32?"])
    conversacion_id: UUID | None = Field(
        default=None, description="Para seguir una conversación; vacío para empezar una nueva"
    )

    @field_validator("mensaje")
    @classmethod
    def _limpiar(cls, valor: str) -> str:
        limpio = limpiar_mensaje(valor)
        if not limpio:
            raise ValueError("El mensaje está vacío")
        return limpio


class UsoChat(BaseModel):
    tokens_entrada: int
    tokens_salida: int
    tokens_cache: int
    costo_usd: float
    rondas: int


class RespuestaChat(BaseModel):
    conversacion_id: UUID
    respuesta: str
    herramientas_usadas: list[str]
    uso: UsoChat


@app.post("/api/v1/chat", tags=["Chat"], summary="Hacer una pregunta al asistente")
def chat(
    peticion: PeticionChat,
    quien: Quien,
    agente: AgenteListo,
    sesion_tienda: SesionTienda,
    sesion_asistente: SesionAsistente,
    reglas: Annotated[limites.Limites, Depends(obtener_limites)],
    origen: Annotated[str, Depends(obtener_origen)],
) -> RespuestaChat:
    limites.verificar(sesion_asistente, quien, origen, reglas)

    if peticion.conversacion_id is None:
        conversacion_id = historial.crear_conversacion(sesion_asistente, quien)
        contexto = []
    else:
        conversacion_id = peticion.conversacion_id
        try:
            contexto = historial.cargar_contexto(sesion_asistente, conversacion_id, quien)
        except historial.ConversacionNoEncontrada as error:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada") from error

    inicio = time.perf_counter()
    try:
        respuesta = agente.responder(sesion_tienda, quien, contexto, peticion.mensaje)
    except ErrorClaude as error:
        registro_log.error("Falló el proveedor de IA (estado %s): %s", error.estado, error)
        sesion_asistente.rollback()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "El asistente no está disponible en este momento"
        ) from error
    latencia_ms = int((time.perf_counter() - inicio) * 1000)

    texto_seguro, bloqueado = filtrar_respuesta(respuesta.texto)
    if bloqueado:
        registro_log.warning("Respuesta bloqueada por el filtro de salida")
        respuesta.texto, respuesta.motivo = texto_seguro, "filtrado"

    historial.guardar_intercambio(
        sesion_asistente, conversacion_id, peticion.mensaje, respuesta, latencia_ms, origen
    )
    sesion_asistente.commit()
    return RespuestaChat(
        conversacion_id=conversacion_id,
        respuesta=respuesta.texto,
        herramientas_usadas=[h.nombre for h in respuesta.herramientas],
        uso=UsoChat(
            tokens_entrada=respuesta.uso.entrada,
            tokens_salida=respuesta.uso.salida,
            tokens_cache=respuesta.uso.cache_lectura + respuesta.uso.cache_escritura,
            costo_usd=float(respuesta.costo_usd),
            rondas=respuesta.rondas,
        ),
    )


class MensajeHistorial(BaseModel):
    autor: str
    texto: str
    fecha: str


@app.get(
    "/api/v1/conversaciones/{conversacion_id}",
    tags=["Chat"],
    summary="Mensajes de una conversación propia",
)
def ver_conversacion(
    conversacion_id: UUID, quien: Quien, sesion_asistente: SesionAsistente
) -> list[MensajeHistorial]:
    try:
        filas = historial.mensajes_de(sesion_asistente, conversacion_id, quien)
    except historial.ConversacionNoEncontrada as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversación no encontrada") from error
    return [
        MensajeHistorial(autor=str(f["autor"]), texto=str(f["texto"]), fecha=str(f["fecha"]))
        for f in filas
    ]


@app.get(
    "/api/v1/herramientas/productos",
    tags=["Herramientas"],
    summary="Buscar productos (la misma herramienta que usa el agente)",
)
def herramienta_productos(
    sesion: SesionTienda,
    filtros: Annotated[FiltrosBusqueda, Query()],
) -> list[ProductoResumen]:
    return buscar_productos(sesion, filtros)
