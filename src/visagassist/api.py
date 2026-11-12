"""API HTTP de VisagAssist (FastAPI). La documentación interactiva queda en /docs."""

from typing import Annotated

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from visagassist import __version__
from visagassist.db import obtener_sesion
from visagassist.herramientas.productos import FiltrosBusqueda, ProductoResumen, buscar_productos

app = FastAPI(
    title="VisagAssist",
    version=__version__,
    description=(
        "Asistente con IA para la tienda VisagShop. Responde preguntas en español "
        "consultando los datos reales de la tienda mediante herramientas fijas de solo lectura."
    ),
)

SesionBD = Annotated[Session, Depends(obtener_sesion)]


class Estado(BaseModel):
    estado: str
    aplicacion: str
    version: str
    base_de_datos: str


@app.get("/api/v1/estado", tags=["Estado"], summary="Salud del servicio")
def estado(sesion: SesionBD) -> Estado:
    try:
        sesion.execute(text("SELECT 1"))
        base = "OK"
    except Exception:  # la salud no debe romperse si la base está caída
        base = "sin conexión"
    return Estado(estado="OK", aplicacion="VisagAssist", version=__version__, base_de_datos=base)


@app.get(
    "/api/v1/herramientas/productos",
    tags=["Herramientas"],
    summary="Buscar productos (la misma herramienta que usa el agente)",
)
def herramienta_productos(
    sesion: SesionBD,
    filtros: Annotated[FiltrosBusqueda, Query()],
) -> list[ProductoResumen]:
    return buscar_productos(sesion, filtros)
