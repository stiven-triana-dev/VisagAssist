import re
import ssl
from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import URL, Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker

from visagassist.config import obtener_configuracion

TIEMPO_MAXIMO_CONSULTA_MS = 5000


def limpiar_url(texto: str) -> str:
    encontrada = re.search(r"postgres(?:ql)?(?:\+\w+)?://[^\s'\"]+", texto)
    if encontrada is None:
        # Sin mostrar el valor: podría contener la clave.
        raise ValueError("La dirección de la base no es válida: debe empezar por postgresql://")
    return encontrada.group(0)


def preparar_url(url: str) -> tuple[URL, dict[str, Any]]:
    datos_url = make_url(limpiar_url(url))
    if datos_url.drivername in {"postgres", "postgresql"}:
        datos_url = datos_url.set(drivername="postgresql+pg8000")
    argumentos_conexion: dict[str, Any] = {}
    if datos_url.query.get("sslmode") in {"require", "verify-ca", "verify-full"}:
        datos_url = datos_url.difference_update_query(["sslmode", "channel_binding"])
        argumentos_conexion["ssl_context"] = ssl.create_default_context()
    return datos_url, argumentos_conexion


def crear_motor(url: str) -> Engine:
    datos_url, argumentos_conexion = preparar_url(url)
    motor = create_engine(
        datos_url, connect_args=argumentos_conexion, pool_pre_ping=True, pool_size=3, max_overflow=2
    )

    @event.listens_for(motor, "connect")
    def _solo_lectura(conexion_dbapi: Any, _registro: Any) -> None:
        cursor = conexion_dbapi.cursor()
        cursor.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cursor.execute(f"SET statement_timeout = {TIEMPO_MAXIMO_CONSULTA_MS}")
        cursor.close()
        conexion_dbapi.commit()

    return motor


@lru_cache
def motor() -> Engine:
    return crear_motor(str(obtener_configuracion().database_url))


def fabrica_sesiones(m: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=m, autoflush=False, expire_on_commit=False)


def obtener_sesion() -> Iterator[Session]:
    with fabrica_sesiones(motor())() as sesion:
        yield sesion
