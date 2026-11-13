"""Corre las evaluaciones del asistente contra Claude real y guarda resultados y conversaciones.

Uso (desde la carpeta VisagAssist, con el .env configurado):
    python -m evaluaciones.ejecutar --casos c01,c02      # prueba piloto con pocos casos
    python -m evaluaciones.ejecutar                       # todos los casos
    python -m evaluaciones.ejecutar --aprobar-arnes       # solo la persona dueña del proyecto,
                                                          # después de revisar cambios del ejecutor

Cada pregunta pasa por la ruta REAL /api/v1/chat (pase firmado, límites, agente, herramientas
sobre la base, filtro de salida). Lo único que se agrega es una "grabadora" alrededor del
cliente de Claude para guardar la conversación completa de cada caso.

Salida en .claude/hillclimb/asistente/<variante>/:
  results.jsonl  una línea por caso (calificación, tokens, latencia), escrita al terminar cada uno
  traces/        la conversación completa de cada caso
  errors.jsonl   intentos que fallaron por algo ajeno al modelo (red, tiempo máximo...)
Se puede interrumpir y volver a correr: salta los casos que ya están en results.jsonl.
"""

import argparse
import copy
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TiempoAgotado
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from evaluaciones.calificar import calificar
from visagassist import api
from visagassist.agente import Agente, instrucciones_para
from visagassist.claude import ClienteClaude, RespuestaClaude, Uso, costo_usd
from visagassist.config import obtener_configuracion
from visagassist.identidad import Identidad, Rol, emitir_pase
from visagassist.limites import Limites
from visagassist.proveedores import elegir_proveedor

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_EVAL = RAIZ / ".claude" / "hillclimb" / "asistente"
ARCHIVOS_DEL_ARNES = [
    RAIZ / "evaluaciones" / "ejecutar.py",
    RAIZ / "evaluaciones" / "calificar.py",
    RAIZ / "evaluaciones" / "casos.json",
]

# Personas de la copia local de la tienda (base visag_legacy).
PERSONAS = {
    "invitado": None,
    "sofia": Identidad(Rol.CLIENTE, UUID("e8e092b5-ec08-40fc-a8e5-04a1ba0d5a65"), "Sofía"),
    "jose": Identidad(Rol.CLIENTE, UUID("ed759787-00fe-44b6-8c84-f37ede0f351c"), "José"),
    "admin": Identidad(Rol.ADMINISTRADOR),
}
ESTADO_INICIAL = {
    "flow": "asistente",
    "metrics": [
        {"id": "aprobado", "label": "Aprobado", "kind": "binary"},
        {"id": "herramienta", "label": "Herramienta", "kind": "binary"},
        {"id": "contenido", "label": "Contenido", "kind": "binary"},
    ],
    "perf_fields": ["latency_s", "tool_calls", "usage"],
    "harness_paths": [str(p.relative_to(RAIZ)) for p in ARCHIVOS_DEL_ARNES],
}


class Grabadora:
    """Envuelve al cliente real de Claude y guarda cada petición con su respuesta."""

    def __init__(self, cliente: ClienteClaude) -> None:
        self._cliente = cliente
        self.llamadas: list[tuple[dict[str, Any], RespuestaClaude]] = []

    def crear_mensaje(self, peticion: dict[str, Any]) -> RespuestaClaude:
        respuesta = self._cliente.crear_mensaje(peticion)
        self.llamadas.append((copy.deepcopy(peticion), respuesta))
        return respuesta


# ----------------------------------------------------------------- arnés


def huella_del_arnes() -> str:
    resumen = hashlib.sha256()
    for archivo in ARCHIVOS_DEL_ARNES:
        resumen.update(archivo.name.encode())
        resumen.update(archivo.read_bytes())
    return resumen.hexdigest()


def revisar_arnes(aprobar: bool) -> None:
    """Si el ejecutor, el calificador o los casos cambian, alguien debe aprobarlo a propósito."""
    CARPETA_EVAL.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA_EVAL / "_state.json"
    estado = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else ESTADO_INICIAL
    actual = huella_del_arnes()
    if aprobar:
        estado["harness_sha"] = actual
        ruta.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Arnés aprobado.")
        return
    if estado.get("harness_sha") != actual:
        print(
            "El ejecutor, el calificador o los casos cambiaron desde la última aprobación.\n"
            "Revisa los cambios y corre de nuevo con --aprobar-arnes.",
            file=sys.stderr,
        )
        sys.exit(2)


# ----------------------------------------------------------------- un caso


def correr_caso(
    cliente: TestClient, grabadora: Grabadora, caso: dict[str, Any], secreto: str
) -> dict[str, Any]:
    persona = PERSONAS[caso["rol"]]
    encabezados = {"Authorization": f"Bearer {emitir_pase(persona, secreto)}"} if persona else {}

    conversacion_id = None
    for previa in caso.get("previas") or []:
        r = cliente.post("/api/v1/chat", json={"mensaje": previa}, headers=encabezados)
        r.raise_for_status()
        conversacion_id = r.json()["conversacion_id"]

    desde = len(grabadora.llamadas)
    inicio = time.perf_counter()
    cuerpo: dict[str, Any] = {"mensaje": caso["pregunta"]}
    if conversacion_id:
        cuerpo["conversacion_id"] = conversacion_id
    r = cliente.post("/api/v1/chat", json=cuerpo, headers=encabezados)
    latencia = time.perf_counter() - inicio
    r.raise_for_status()
    datos = r.json()

    llamadas = grabadora.llamadas[desde:]
    if not llamadas:
        raise RuntimeError("La pregunta no llegó al modelo")
    uso = Uso()
    for _peticion, respuesta in llamadas:
        uso += respuesta.uso
    ultima_peticion, ultima_respuesta = llamadas[-1]
    modelo_pedido = str(ultima_peticion["model"])
    if not ultima_respuesta.modelo.startswith(modelo_pedido):
        raise RuntimeError(f"Respondió {ultima_respuesta.modelo} en vez de {modelo_pedido}")

    calificacion = calificar(caso, datos["respuesta"], datos["herramientas_usadas"])
    return {
        "fila": {
            "prompt_id": caso["id"],
            "prompt": caso["pregunta"],
            "tags": [caso["grupo"], caso["rol"]],
            "stop_reason": ultima_respuesta.motivo_parada,
            "status": "truncated" if ultima_respuesta.motivo_parada == "max_tokens" else "ok",
            **calificacion,
            "model": ultima_respuesta.modelo,
            "usage": {
                "input_tokens": uso.entrada,
                "output_tokens": uso.salida,
                "cache_read_input_tokens": uso.cache_lectura,
                "cache_creation_input_tokens": uso.cache_escritura,
            },
            "latency_s": round(latencia, 2),
            "tool_calls": len(datos["herramientas_usadas"]),
            "meta": {
                "respuesta": datos["respuesta"],
                "herramientas": datos["herramientas_usadas"],
                "costo_usd": str(costo_usd(ultima_respuesta.modelo, uso)),
            },
        },
        "traza": traza(ultima_peticion, ultima_respuesta, caso["rol"]),
    }


def traza(peticion: dict[str, Any], respuesta: RespuestaClaude, rol: str) -> list[dict[str, Any]]:
    """Conversación completa en el formato del visor de reportes."""
    turnos: list[dict[str, Any]] = [
        {"role": "system", "content": peticion["system"][0]["text"]},
    ]
    mensajes = [*peticion["messages"], {"role": "assistant", "content": respuesta.contenido}]
    for mensaje in mensajes:
        contenido = mensaje["content"]
        if isinstance(contenido, str):
            turnos.append(
                {"role": "user" if mensaje["role"] == "user" else "assistant", "content": contenido}
            )
            continue
        pensamiento = ""
        for bloque in contenido:
            tipo = bloque.get("type")
            if tipo == "thinking":
                pensamiento = bloque.get("thinking", "")
            elif tipo == "text":
                turno = {"role": "assistant", "content": bloque.get("text", "")}
                if pensamiento:
                    turno["thinking"], pensamiento = pensamiento, ""
                turnos.append(turno)
            elif tipo == "tool_use":
                turno = {
                    "role": "tool_call",
                    "name": bloque.get("name"),
                    "content": json.dumps(bloque.get("input", {}), indent=2, ensure_ascii=False),
                }
                if pensamiento:
                    turno["thinking"], pensamiento = pensamiento, ""
                turnos.append(turno)
            elif tipo == "tool_result":
                turnos.append({"role": "tool_result", "content": bloque.get("content", "")})
    return turnos


# ----------------------------------------------------------------- corrida


def intervalo_wilson(aprobados: int, total: int) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    z = 1.96
    p = aprobados / total
    centro = (p + z * z / (2 * total)) / (1 + z * z / total)
    margen = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return max(0.0, centro - margen), min(1.0, centro + margen)


def main() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--variante", default="baseline")
    argumentos.add_argument("--reps", type=int, default=1)
    argumentos.add_argument("--casos", help="ids separados por coma (por defecto, todos)")
    argumentos.add_argument("--tiempo-max", type=float, default=180.0, help="segundos por caso")
    argumentos.add_argument("--aprobar-arnes", action="store_true")
    opciones = argumentos.parse_args()

    revisar_arnes(opciones.aprobar_arnes)
    if opciones.aprobar_arnes:
        return

    configuracion = obtener_configuracion()
    proveedor = elegir_proveedor(configuracion)
    if proveedor is None or configuracion.secreto_identidad is None:
        sys.exit(
            "Faltan la clave de la IA (ANTHROPIC_API_KEY o GEMINI_API_KEY) "
            "o VISAGASSIST_SECRETO en el archivo .env"
        )
    print(f"Proveedor: {proveedor.nombre} · modelo {proveedor.modelo}")
    secreto = configuracion.secreto_identidad.get_secret_value()

    casos: list[dict[str, Any]] = json.loads(
        (RAIZ / "evaluaciones" / "casos.json").read_text(encoding="utf-8")
    )
    if opciones.casos:
        elegidos = set(opciones.casos.split(","))
        casos = [c for c in casos if c["id"] in elegidos]

    carpeta = CARPETA_EVAL / opciones.variante
    (carpeta / "traces").mkdir(parents=True, exist_ok=True)
    resultados = carpeta / "results.jsonl"
    hechos = set()
    if resultados.exists():
        for linea in resultados.read_text(encoding="utf-8").splitlines():
            fila = json.loads(linea)
            hechos.add((fila["prompt_id"], fila.get("rep", 0)))

    grabadora = Grabadora(proveedor.cliente)
    api.app.dependency_overrides[api.obtener_agente] = lambda: Agente(
        grabadora, modelo=proveedor.modelo
    )
    # La evaluación no debe frenarse por los límites de uso de la demo pública.
    api.app.dependency_overrides[api.obtener_limites] = lambda: Limites(
        por_hora=dict.fromkeys(Rol, 100_000), presupuesto_diario_usd=Decimal(1_000)
    )
    print(f"Instrucciones del invitado: {len(instrucciones_para(Rol.INVITADO))} caracteres")

    inicio_total = time.perf_counter()
    with TestClient(api.app) as cliente, ThreadPoolExecutor(max_workers=1) as hilo:
        for rep in range(opciones.reps):
            for caso in casos:
                if (caso["id"], rep) in hechos:
                    continue
                futuro = hilo.submit(correr_caso, cliente, grabadora, caso, secreto)
                try:
                    salida = futuro.result(timeout=opciones.tiempo_max)
                except TiempoAgotado:
                    _error(carpeta, caso["id"], rep, "timeout", "superó el tiempo máximo")
                    print(f"{caso['id']}  TIEMPO AGOTADO")
                    continue
                except Exception as error:  # red, API, base: no es culpa del modelo
                    _error(carpeta, caso["id"], rep, "harness_error", repr(error))
                    print(f"{caso['id']}  ERROR {error!r}")
                    continue
                fila = {**salida["fila"], "rep": rep}
                with resultados.open("a", encoding="utf-8") as archivo:
                    archivo.write(json.dumps(fila, ensure_ascii=False) + "\n")
                (carpeta / "traces" / f"{caso['id']}_rep{rep}.json").write_text(
                    json.dumps(salida["traza"], indent=2, ensure_ascii=False), encoding="utf-8"
                )
                marca = "OK " if fila["grade"]["aprobado"] else "NO "
                print(
                    f"{caso['id']}  {marca} {fila['latency_s']:>5}s  "
                    + fila["explanation"]["aprobado"]
                )

    resumen(resultados, time.perf_counter() - inicio_total)


def _error(carpeta: Path, caso_id: str, rep: int, clase: str, detalle: str) -> None:
    with (carpeta / "errors.jsonl").open("a", encoding="utf-8") as archivo:
        archivo.write(
            json.dumps({"prompt_id": caso_id, "rep": rep, "class": clase, "detail": detalle}) + "\n"
        )


def resumen(resultados: Path, segundos: float) -> None:
    if not resultados.exists():
        print("Sin resultados.")
        return
    filas = [json.loads(linea) for linea in resultados.read_text(encoding="utf-8").splitlines()]
    validas = [f for f in filas if f["status"] == "ok"]
    aprobados = sum(1 for f in validas if f["grade"]["aprobado"] == 1.0)
    bajo, alto = intervalo_wilson(aprobados, len(validas))
    costo = sum(Decimal(f["meta"]["costo_usd"]) for f in filas)
    print(
        f"\nAprobados: {aprobados}/{len(validas)} ({aprobados / max(len(validas), 1):.0%}, "
        f"IC 95 %: {bajo:.0%}-{alto:.0%}) · costo ${costo:.4f} USD · {segundos:.0f} s"
    )


if __name__ == "__main__":
    main()
