"""Lectura de la configuración desde variables de entorno."""

import pytest
from pydantic import ValidationError

from visagassist.config import Configuracion


def test_lee_la_url_de_la_base_y_el_limite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+pg8000://lector:clave@localhost:5432/tienda")
    monkeypatch.setenv("LIMITE_RESULTADOS", "15")
    configuracion = Configuracion(_env_file=None)  # type: ignore[call-arg]
    assert configuracion.database_url.hosts()[0]["host"] == "localhost"
    assert configuracion.limite_resultados == 15


def test_sin_url_de_base_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Configuracion(_env_file=None)  # type: ignore[call-arg]


def test_rechaza_una_url_que_no_es_de_postgresql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "mysql://usuario:clave@localhost/tienda")
    with pytest.raises(ValidationError):
        Configuracion(_env_file=None)  # type: ignore[call-arg]
