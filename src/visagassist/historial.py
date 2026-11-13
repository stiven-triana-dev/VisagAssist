"""Historial de conversaciones y costos, en la base PROPIA del asistente.

Es una base distinta a la de VisagShop: allí el asistente solo lee; aquí escribe sus
conversaciones, qué herramientas usó, cuántos tokens gastó y cuánto costó cada respuesta.
La estructura la crean las migraciones de Alembic (carpeta migraciones/).
"""

from collections.abc import Iterator
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, sessionmaker

from visagassist.agente import RespuestaAgente, Turno
from visagassist.config import obtener_configuracion
from visagassist.db import preparar_url
from visagassist.identidad import Identidad

metadatos_asistente = MetaData()

conversaciones = Table(
    "conversaciones",
    metadatos_asistente,
    Column("id", Uuid, primary_key=True),
    Column("propietario", String(60), nullable=False, index=True),
    Column("rol", String(20), nullable=False),
    Column("creada_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("actualizada_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

mensajes = Table(
    "mensajes",
    metadatos_asistente,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column(
        "conversacion_id",
        Uuid,
        ForeignKey("conversaciones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("autor", String(10), nullable=False),
    Column("texto", Text, nullable=False),
    Column("modelo", String(40)),
    Column("motivo", String(20)),
    Column("herramientas", JSONB, nullable=False, server_default="[]"),
    Column("tokens_entrada", Integer, nullable=False, server_default="0"),
    Column("tokens_salida", Integer, nullable=False, server_default="0"),
    Column("tokens_cache_lectura", Integer, nullable=False, server_default="0"),
    Column("tokens_cache_escritura", Integer, nullable=False, server_default="0"),
    Column("costo_usd", Numeric(12, 6), nullable=False, server_default="0"),
    Column("latencia_ms", Integer),
    Column("origen", String(64)),  # huella (HMAC) de la IP, para el límite de invitados
    Column("creado_en", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("autor IN ('usuario', 'asistente')", name="mensajes_autor_valido"),
)

# Cuántos mensajes anteriores se le envían al modelo como contexto.
MENSAJES_DE_CONTEXTO = 20


class ConversacionNoEncontrada(LookupError):
    """No existe o es de otra persona (se responde igual para no revelar cuál de las dos)."""


def crear_conversacion(sesion: Session, quien: Identidad) -> UUID:
    identificador = uuid4()
    sesion.execute(
        insert(conversaciones).values(
            id=identificador, propietario=quien.clave_propietario, rol=quien.rol.value
        )
    )
    return identificador


def _verificar_propietario(sesion: Session, conversacion_id: UUID, quien: Identidad) -> None:
    propietario = sesion.scalar(
        select(conversaciones.c.propietario).where(conversaciones.c.id == conversacion_id)
    )
    if propietario != quien.clave_propietario:
        raise ConversacionNoEncontrada(str(conversacion_id))


def cargar_contexto(sesion: Session, conversacion_id: UUID, quien: Identidad) -> list[Turno]:
    """Últimos mensajes de la conversación, en orden, para dárselos al modelo."""
    _verificar_propietario(sesion, conversacion_id, quien)
    filas = sesion.execute(
        select(mensajes.c.autor, mensajes.c.texto)
        .where(mensajes.c.conversacion_id == conversacion_id)
        .order_by(mensajes.c.id.desc())
        .limit(MENSAJES_DE_CONTEXTO)
    ).all()
    turnos = [Turno(autor, texto) for autor, texto in reversed(filas)]
    # La API exige que la conversación empiece con el usuario.
    while turnos and turnos[0].rol != "usuario":
        turnos.pop(0)
    return turnos


def guardar_intercambio(
    sesion: Session,
    conversacion_id: UUID,
    pregunta: str,
    respuesta: RespuestaAgente,
    latencia_ms: int,
    origen: str | None = None,
) -> None:
    sesion.execute(
        insert(mensajes).values(
            conversacion_id=conversacion_id, autor="usuario", texto=pregunta, origen=origen
        )
    )
    sesion.execute(
        insert(mensajes).values(
            conversacion_id=conversacion_id,
            autor="asistente",
            texto=respuesta.texto,
            modelo=respuesta.modelo,
            motivo=respuesta.motivo,
            herramientas=[asdict(h) for h in respuesta.herramientas],
            tokens_entrada=respuesta.uso.entrada,
            tokens_salida=respuesta.uso.salida,
            tokens_cache_lectura=respuesta.uso.cache_lectura,
            tokens_cache_escritura=respuesta.uso.cache_escritura,
            costo_usd=respuesta.costo_usd,
            latencia_ms=latencia_ms,
        )
    )
    sesion.execute(
        update(conversaciones)
        .where(conversaciones.c.id == conversacion_id)
        .values(actualizada_en=func.now())
    )


def preguntas_desde(
    sesion: Session, desde: datetime, *, propietario: str | None = None, origen: str | None = None
) -> int:
    """Preguntas hechas desde un momento, por dueño (cuenta) o por origen (invitados)."""
    consulta = (
        select(func.count())
        .select_from(mensajes.join(conversaciones))
        .where(mensajes.c.autor == "usuario", mensajes.c.creado_en >= desde)
    )
    if propietario is not None:
        consulta = consulta.where(conversaciones.c.propietario == propietario)
    if origen is not None:
        consulta = consulta.where(mensajes.c.origen == origen)
    return int(sesion.scalar(consulta) or 0)


def gasto_desde(sesion: Session, desde: datetime) -> Decimal:
    """Costo total en dólares de las respuestas desde un momento (todas las personas)."""
    total = sesion.scalar(
        select(func.coalesce(func.sum(mensajes.c.costo_usd), 0)).where(
            mensajes.c.creado_en >= desde
        )
    )
    return Decimal(total or 0)


def mensajes_de(
    sesion: Session, conversacion_id: UUID, quien: Identidad
) -> list[dict[str, object]]:
    _verificar_propietario(sesion, conversacion_id, quien)
    filas = sesion.execute(
        select(mensajes.c.autor, mensajes.c.texto, mensajes.c.creado_en)
        .where(mensajes.c.conversacion_id == conversacion_id)
        .order_by(mensajes.c.id)
    ).all()
    return [{"autor": a, "texto": t, "fecha": f} for a, t, f in filas]


# ----------------------------------------------------------------- conexión


@lru_cache
def motor_asistente() -> Engine:
    url = obtener_configuracion().database_url_asistente
    if url is None:
        raise RuntimeError("Falta DATABASE_URL_ASISTENTE (base propia del asistente)")
    datos_url, argumentos = preparar_url(str(url))
    return create_engine(datos_url, connect_args=argumentos, pool_pre_ping=True, pool_size=3)


def obtener_sesion_asistente() -> Iterator[Session]:
    with sessionmaker(bind=motor_asistente(), expire_on_commit=False)() as sesion:
        yield sesion
