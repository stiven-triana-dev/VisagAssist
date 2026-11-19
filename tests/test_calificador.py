import json
import re
from pathlib import Path
from typing import Any

import pytest

from evaluaciones.calificar import calificar, normalizar

CARPETA = Path(__file__).parent.parent / "evaluaciones"
CASOS: list[dict[str, Any]] = json.loads((CARPETA / "casos.json").read_text(encoding="utf-8"))
ORACULOS: dict[str, dict[str, Any]] = json.loads(
    (CARPETA / "oraculos.json").read_text(encoding="utf-8")
)
IDS = [c["id"] for c in CASOS]


def test_hay_entre_15_y_100_casos_con_ids_unicos() -> None:
    assert 15 <= len(CASOS) <= 100
    assert len(set(IDS)) == len(IDS)
    assert set(ORACULOS) == set(IDS)


@pytest.mark.parametrize("caso", CASOS, ids=IDS)
def test_cada_caso_esta_bien_formado(caso: dict[str, Any]) -> None:
    assert caso["rol"] in {"invitado", "sofia", "jose", "admin"}
    assert caso["pregunta"].strip()
    assert caso["porque"].strip()
    tiene_regla = any(
        caso.get(k) for k in ("contiene_todos", "no_contiene", "no_coincide", "coincide")
    )
    assert tiene_regla, "cada caso debe revisar algo de la respuesta"
    for patron in (caso.get("no_coincide") or []) + (caso.get("coincide") or []):
        re.compile(patron)


@pytest.mark.parametrize("caso", CASOS, ids=IDS)
def test_la_respuesta_de_referencia_aprueba(caso: dict[str, Any]) -> None:
    oraculo = ORACULOS[caso["id"]]
    resultado = calificar(caso, oraculo["respuesta"], oraculo["herramientas"])
    assert resultado["grade"]["aprobado"] == 1.0, resultado["explanation"]


@pytest.mark.parametrize("caso", CASOS, ids=IDS)
def test_una_respuesta_vacia_reprueba(caso: dict[str, Any]) -> None:
    assert calificar(caso, "", [])["grade"]["aprobado"] == 0.0


SABER_QUE_NO_SE_SABE = {"c19", "c21"}


@pytest.mark.parametrize(
    "caso", [c for c in CASOS if c["id"] not in SABER_QUE_NO_SE_SABE], ids=lambda c: c["id"]
)
def test_no_se_sabe_sin_herramientas_reprueba(caso: dict[str, Any]) -> None:
    resultado = calificar(caso, "No sé.", [])
    assert resultado["grade"]["aprobado"] == 0.0


def test_respuesta_segura_pero_de_otra_pregunta_reprueba() -> None:
    caso = next(c for c in CASOS if c["id"] == "c03")
    otra = ORACULOS["c12"]  # habla del jean p042, no de la sudadera
    assert calificar(caso, otra["respuesta"], ["buscar_productos"])["grade"]["aprobado"] == 0.0


def test_inventar_tallas_reprueba() -> None:
    caso = next(c for c in CASOS if c["id"] == "c18")
    inventada = "Los Jordan negros vienen en tallas 40, 41 y 42."
    assert calificar(caso, inventada, ["buscar_productos"])["grade"]["aprobado"] == 0.0


def test_datos_de_otra_clienta_reprueban() -> None:
    caso = next(c for c in CASOS if c["id"] == "c28")
    fuga = "El pedido VS-1001 está confirmado por $250.000."
    assert calificar(caso, fuga, ["mis_pedidos"])["grade"]["aprobado"] == 0.0


def test_metricas_separadas() -> None:
    caso = next(c for c in CASOS if c["id"] == "c03")
    resultado = calificar(caso, "Cuesta $85.000: productDetail?id=p095", [])
    assert resultado["grade"] == {"aprobado": 0.0, "herramienta": 0.0, "contenido": 1.0}


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("$130.000", "$130000"), ("130,000 pesos", "130000 pesos"), ("Sofía Peña", "sofia pena")],
)
def test_normalizar(entrada: str, esperado: str) -> None:
    assert normalizar(entrada) == esperado
