"""Preparación de las pruebas.

Las pruebas de integración necesitan un PostgreSQL real. Se indica con la variable
TEST_DATABASE_URL, que debe apuntar a una base VACÍA de pruebas con un usuario dueño
(por ejemplo postgresql+pg8000://postgres:postgres@localhost:5432/visagassist_test).

Con ese usuario se crea la estructura de VisagShop, se cargan datos de prueba y se crea
un rol de SOLO LECTURA. La aplicación se conecta con ese rol, igual que en producción.
Si TEST_DATABASE_URL no existe, esas pruebas se omiten y las demás corren normal.
"""

import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from visagassist.api import app
from visagassist.db import crear_motor, fabrica_sesiones, obtener_sesion

DATOS = Path(__file__).parent / "datos"
ROL_LECTURA = "visagassist_prueba_lectura"
CLAVE_LECTURA = "clave-solo-pruebas"


def _url_dueno() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Sin TEST_DATABASE_URL: se omiten las pruebas con PostgreSQL real")
    return url


def _sentencias(sql: str) -> list[str]:
    """Separa un archivo .sql en sentencias (pg8000 ejecuta una por llamada).

    Basta con cortar en el ";" del final de línea: en estos archivos ningún texto entre
    comillas termina una línea con ";".
    """
    partes = [p.strip() for p in re.split(r";[ \t]*\r?\n", sql + "\n")]
    sin_comentarios = (
        "\n".join(linea for linea in p.splitlines() if not linea.strip().startswith("--"))
        for p in partes
    )
    return [p.strip() for p in sin_comentarios if p.strip()]


def _preparar_base(dueno: Engine) -> None:
    with dueno.begin() as con:
        con.execute(text("DROP SCHEMA public CASCADE"))
        con.execute(text("CREATE SCHEMA public"))
        for archivo in ("esquema_visagshop.sql", "datos_prueba.sql"):
            for sentencia in _sentencias((DATOS / archivo).read_text(encoding="utf-8")):
                con.exec_driver_sql(sentencia)
        existe = con.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :rol"), {"rol": ROL_LECTURA}
        ).first()
        if not existe:
            con.exec_driver_sql(f"CREATE ROLE {ROL_LECTURA} LOGIN PASSWORD '{CLAVE_LECTURA}'")
        base = con.execute(text("SELECT current_database()")).scalar_one()
        con.exec_driver_sql(f'GRANT CONNECT ON DATABASE "{base}" TO {ROL_LECTURA}')
        con.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {ROL_LECTURA}")
        con.exec_driver_sql(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ROL_LECTURA}")


@pytest.fixture(scope="session")
def motor_lectura() -> Iterator[Engine]:
    url = _url_dueno()
    dueno = create_engine(url)
    _preparar_base(dueno)
    dueno.dispose()
    url_lectura = make_url(url).set(username=ROL_LECTURA, password=CLAVE_LECTURA)
    motor = crear_motor(url_lectura.render_as_string(hide_password=False))
    yield motor
    motor.dispose()


@pytest.fixture
def sesion(motor_lectura: Engine) -> Iterator[Session]:
    with fabrica_sesiones(motor_lectura)() as s:
        yield s


@pytest.fixture
def cliente(motor_lectura: Engine) -> Iterator[TestClient]:
    def _sesion_de_prueba() -> Iterator[Session]:
        with fabrica_sesiones(motor_lectura)() as s:
            yield s

    app.dependency_overrides[obtener_sesion] = _sesion_de_prueba
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
