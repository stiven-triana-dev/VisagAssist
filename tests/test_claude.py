"""Cliente HTTP de Claude con un transporte simulado: no hay llamadas reales ni gasto."""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from visagassist.claude import (
    URL_API,
    VERSION_API,
    ClienteHTTPClaude,
    ErrorClaude,
    Uso,
    costo_usd,
)

RESPUESTA_OK = {
    "id": "msg_1",
    "model": "claude-haiku-5-5",
    "stop_reason": "end_turn",
    "content": [{"type": "text", "text": "Hola"}],
    "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50},
}


class Servidor:
    """Devuelve las respuestas en orden y guarda lo que recibió."""

    def __init__(self, *respuestas: httpx.Response | Exception) -> None:
        self.respuestas = list(respuestas)
        self.peticiones: list[httpx.Request] = []

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        self.peticiones.append(peticion)
        siguiente = self.respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


def cliente(servidor: Servidor, esperas: list[float] | None = None) -> ClienteHTTPClaude:
    lista = esperas if esperas is not None else []
    return ClienteHTTPClaude(
        "clave-de-prueba", transporte=httpx.MockTransport(servidor), dormir=lista.append
    )


def test_envia_encabezados_y_cuerpo_correctos() -> None:
    servidor = Servidor(httpx.Response(200, json=RESPUESTA_OK))
    peticion: dict[str, Any] = {"model": "claude-haiku-5-5", "max_tokens": 10, "messages": []}
    respuesta = cliente(servidor).crear_mensaje(peticion)

    enviada = servidor.peticiones[0]
    assert str(enviada.url) == URL_API
    assert enviada.headers["x-api-key"] == "clave-de-prueba"
    assert enviada.headers["anthropic-version"] == VERSION_API
    assert json.loads(enviada.content) == peticion
    assert respuesta.contenido == [{"type": "text", "text": "Hola"}]
    assert respuesta.motivo_parada == "end_turn"
    assert respuesta.uso == Uso(entrada=100, salida=20, cache_lectura=50)


@pytest.mark.parametrize("estado", [429, 500, 529])
def test_reintenta_errores_temporales(estado: int) -> None:
    esperas: list[float] = []
    servidor = Servidor(httpx.Response(estado), httpx.Response(200, json=RESPUESTA_OK))
    respuesta = cliente(servidor, esperas).crear_mensaje({"model": "claude-haiku-5-5"})
    assert respuesta.motivo_parada == "end_turn"
    assert len(servidor.peticiones) == 2
    assert esperas == [1.0]


def test_respeta_retry_after_con_tope() -> None:
    esperas: list[float] = []
    servidor = Servidor(
        httpx.Response(429, headers={"retry-after": "3"}),
        httpx.Response(429, headers={"retry-after": "120"}),
        httpx.Response(200, json=RESPUESTA_OK),
    )
    cliente(servidor, esperas).crear_mensaje({})
    assert esperas == [3.0, 10.0]


def test_se_rinde_despues_de_los_reintentos() -> None:
    servidor = Servidor(*(httpx.Response(503) for _ in range(3)))
    with pytest.raises(ErrorClaude) as error:
        cliente(servidor).crear_mensaje({})
    assert error.value.estado == 503
    assert len(servidor.peticiones) == 3


def test_no_reintenta_errores_de_la_peticion() -> None:
    cuerpo = {"type": "error", "error": {"type": "invalid_request_error", "message": "malo"}}
    servidor = Servidor(httpx.Response(400, json=cuerpo))
    with pytest.raises(ErrorClaude, match="invalid_request_error: malo") as error:
        cliente(servidor).crear_mensaje({})
    assert error.value.estado == 400
    assert len(servidor.peticiones) == 1


def test_reintenta_si_falla_la_conexion() -> None:
    servidor = Servidor(httpx.ConnectError("caída"), httpx.Response(200, json=RESPUESTA_OK))
    assert cliente(servidor).crear_mensaje({}).motivo_parada == "end_turn"


def test_sin_conexion_persistente_lanza_error_claro() -> None:
    servidor = Servidor(*(httpx.ConnectError("caída") for _ in range(3)))
    with pytest.raises(ErrorClaude, match="Sin conexión"):
        cliente(servidor).crear_mensaje({})


def test_costo_con_haiku() -> None:
    uso = Uso(entrada=1_000_000, salida=1_000_000, cache_lectura=1_000_000, cache_escritura=0)
    # 0,10 (entrada) + 0,50 (salida) + 0,01 (lectura de caché a 0,1×)
    assert costo_usd("claude-haiku-5-5", uso) == Decimal("0.610000")


def test_costo_de_escritura_en_cache() -> None:
    assert costo_usd("claude-haiku-5-5", Uso(cache_escritura=1_000_000)) == Decimal("0.125000")


def test_costo_de_una_pregunta_tipica_es_una_fraccion_de_centavo() -> None:
    costo = costo_usd("claude-haiku-5-5", Uso(entrada=3000, salida=400))
    assert costo == Decimal("0.000500")


def test_modelo_sin_precio_registrado() -> None:
    with pytest.raises(ValueError, match="No hay precio"):
        costo_usd("modelo-inventado", Uso())


def test_suma_de_usos() -> None:
    assert Uso(1, 2, 3, 4) + Uso(10, 20, 30, 40) == Uso(11, 22, 33, 44)
