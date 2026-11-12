"""Rutas HTTP de VisagAssist."""

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integracion


def test_estado_responde_ok_con_base_conectada(cliente: TestClient) -> None:
    respuesta = cliente.get("/api/v1/estado")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "OK"
    assert cuerpo["aplicacion"] == "VisagAssist"
    assert cuerpo["base_de_datos"] == "OK"


def test_herramienta_de_productos_por_http(cliente: TestClient) -> None:
    respuesta = cliente.get(
        "/api/v1/herramientas/productos", params={"categoria": "gorras", "limite": 5}
    )
    assert respuesta.status_code == 200
    assert [p["id"] for p in respuesta.json()] == ["p001", "p002"]
    assert respuesta.json()[0]["tallas"] == ["Ajustable"]


@pytest.mark.parametrize("parametros", [{"limite": 99}, {"precio_maximo": -5}])
def test_argumentos_invalidos_devuelven_422(
    cliente: TestClient, parametros: dict[str, int]
) -> None:
    assert cliente.get("/api/v1/herramientas/productos", params=parametros).status_code == 422


def test_documentacion_swagger_disponible(cliente: TestClient) -> None:
    assert cliente.get("/docs").status_code == 200
    esquema = cliente.get("/openapi.json").json()
    assert esquema["info"]["title"] == "VisagAssist"
    assert "/api/v1/herramientas/productos" in esquema["paths"]
