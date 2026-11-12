"""Validación de los argumentos de la herramienta (no necesitan base de datos)."""

import pytest
from pydantic import ValidationError

from visagassist.herramientas.productos import FiltrosBusqueda, _normalizar


def test_valores_por_defecto() -> None:
    filtros = FiltrosBusqueda()
    assert filtros.texto is None
    assert filtros.limite == 10


@pytest.mark.parametrize(
    "argumentos",
    [
        {"texto": "x" * 81},
        {"precio_maximo": -1},
        {"limite": 0},
        {"limite": 21},
        {"talla": "x" * 26},
        {"categoria": "x" * 71},
    ],
)
def test_rechaza_argumentos_fuera_de_rango(argumentos: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        FiltrosBusqueda(**argumentos)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("Sudadera Básica", "sudadera basica"),
        ("  ÑANDÚ  ", "nandu"),
        ("pingüino", "pinguino"),
        ("JEAN", "jean"),
    ],
)
def test_normaliza_tildes_mayusculas_y_espacios(entrada: str, esperado: str) -> None:
    assert _normalizar(entrada) == esperado
