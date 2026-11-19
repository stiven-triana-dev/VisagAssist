import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.orm import Session

from visagassist.agente import Agente
from visagassist.claude import ClienteHTTPClaude, ErrorClaude, Uso, costo_usd
from visagassist.config import Configuracion
from visagassist.gemini import (
    PARTE_ORIGINAL,
    URL_BASE,
    ClienteGemini,
    traducir_peticion,
    traducir_respuesta,
)
from visagassist.identidad import Identidad, Rol
from visagassist.proveedores import elegir_proveedor

PETICION: dict[str, Any] = {
    "model": "gemini-flash-latest",
    "max_tokens": 1000,
    "cache_control": {"type": "ephemeral"},
    "output_config": {"effort": "low"},
    "system": [{"type": "text", "text": "Eres VisagAssist."}],
    "tools": [
        {
            "name": "ver_producto",
            "description": "Detalle de un producto.",
            "input_schema": {
                "type": "object",
                "properties": {"producto_id": {"type": "string"}},
                "additionalProperties": False,
            },
        }
    ],
    "messages": [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "¡Hola!"},
        {"role": "user", "content": "¿y el p005?"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "ver_producto",
                    "input": {"producto_id": "p005"},
                }
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": '{"precio": 1}'}],
        },
    ],
}


def gemini(*partes: dict[str, Any], motivo: str = "STOP", **extra: Any) -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"role": "model", "parts": list(partes)}, "finishReason": motivo}
        ],
        "usageMetadata": {
            "promptTokenCount": 900,
            "candidatesTokenCount": 40,
            "thoughtsTokenCount": 60,
        },
        "modelVersion": "gemini-flash-latest",
        **extra,
    }


def test_traduce_sistema_herramientas_y_limite() -> None:
    cuerpo = traducir_peticion(PETICION)
    assert cuerpo["systemInstruction"] == {"parts": [{"text": "Eres VisagAssist."}]}
    declaracion = cuerpo["tools"][0]["functionDeclarations"][0]
    assert declaracion["name"] == "ver_producto"
    assert declaracion["parametersJsonSchema"]["properties"] == {"producto_id": {"type": "string"}}
    assert cuerpo["generationConfig"] == {"maxOutputTokens": 1000}
    assert "cache_control" not in cuerpo
    assert "output_config" not in cuerpo


def test_traduce_la_conversacion_con_roles_y_resultados_de_herramientas() -> None:
    contenidos = traducir_peticion(PETICION)["contents"]
    assert [c["role"] for c in contenidos] == ["user", "model", "user", "model", "user"]
    assert contenidos[1]["parts"] == [{"text": "¡Hola!"}]
    assert contenidos[3]["parts"] == [
        {"functionCall": {"id": "t1", "name": "ver_producto", "args": {"producto_id": "p005"}}}
    ]
    assert contenidos[4]["parts"] == [
        {
            "functionResponse": {
                "id": "t1",
                "name": "ver_producto",
                "response": {"resultado": '{"precio": 1}'},
            }
        }
    ]


def test_un_error_de_herramienta_va_como_error() -> None:
    peticion = json.loads(json.dumps(PETICION))
    peticion["messages"][-1]["content"][0]["is_error"] = True
    parte = traducir_peticion(peticion)["contents"][-1]["parts"][0]
    assert parte["functionResponse"]["response"] == {"error": '{"precio": 1}'}


def test_las_partes_de_gemini_vuelven_intactas_con_su_firma() -> None:
    original = {
        "functionCall": {"id": "g1", "name": "ver_producto", "args": {"producto_id": "p001"}},
        "thoughtSignature": "firma-opaca",
    }
    respuesta = traducir_respuesta(gemini(original), "gemini-flash-latest")
    peticion = {
        "model": "gemini-flash-latest",
        "messages": [
            {"role": "user", "content": "?"},
            {"role": "assistant", "content": respuesta.contenido},
        ],
    }
    assert traducir_peticion(peticion)["contents"][1]["parts"] == [original]


def test_llamada_a_herramienta_se_vuelve_tool_use() -> None:
    respuesta = traducir_respuesta(
        gemini(
            {"functionCall": {"id": "g1", "name": "ver_producto", "args": {"producto_id": "p001"}}}
        ),
        "gemini-flash-latest",
    )
    assert respuesta.motivo_parada == "tool_use"
    bloque = respuesta.contenido[0]
    assert (bloque["type"], bloque["id"], bloque["name"], bloque["input"]) == (
        "tool_use",
        "g1",
        "ver_producto",
        {"producto_id": "p001"},
    )


def test_llamada_sin_id_recibe_uno_estable() -> None:
    respuesta = traducir_respuesta(
        gemini({"text": "Busco..."}, {"functionCall": {"name": "listar_categorias"}}), "m"
    )
    assert respuesta.contenido[1]["id"] == "gemini_1"
    assert respuesta.contenido[1]["input"] == {}


def test_texto_final_y_uso_de_tokens() -> None:
    respuesta = traducir_respuesta(gemini({"text": "Cuesta $85.000."}), "gemini-flash-latest")
    assert respuesta.motivo_parada == "end_turn"
    assert respuesta.contenido[0]["text"] == "Cuesta $85.000."
    assert respuesta.uso == Uso(entrada=900, salida=100)


def test_el_razonamiento_no_se_muestra_como_texto() -> None:
    respuesta = traducir_respuesta(
        gemini({"text": "pensando...", "thought": True}, {"text": "Hola"}), "m"
    )
    assert [b["type"] for b in respuesta.contenido] == ["thinking", "text"]
    assert respuesta.contenido[0]["thinking"] == ""


@pytest.mark.parametrize(
    ("motivo", "esperado"),
    [
        ("STOP", "end_turn"),
        ("MAX_TOKENS", "max_tokens"),
        ("SAFETY", "refusal"),
        ("OTHER", "end_turn"),
    ],
)
def test_motivos_de_parada(motivo: str, esperado: str) -> None:
    assert traducir_respuesta(gemini({"text": "x"}, motivo=motivo), "m").motivo_parada == esperado


def test_pregunta_bloqueada_sin_candidatos_es_rechazo() -> None:
    datos = {"promptFeedback": {"blockReason": "SAFETY"}, "usageMetadata": {"promptTokenCount": 10}}
    respuesta = traducir_respuesta(datos, "gemini-flash-latest")
    assert respuesta.motivo_parada == "refusal"
    assert respuesta.contenido == []


def test_tokens_en_cache() -> None:
    datos = gemini({"text": "x"})
    datos["usageMetadata"]["cachedContentTokenCount"] = 300
    assert traducir_respuesta(datos, "m").uso == Uso(entrada=600, salida=100, cache_lectura=300)


def test_gemini_del_plan_gratuito_cuesta_cero() -> None:
    assert costo_usd("gemini-flash-latest", Uso(entrada=10**6, salida=10**6)) == Decimal("0.000000")


def test_cliente_usa_endpoint_y_encabezado_de_google() -> None:
    peticiones: list[httpx.Request] = []

    def servidor(peticion: httpx.Request) -> httpx.Response:
        peticiones.append(peticion)
        return httpx.Response(200, json=gemini({"text": "hola"}))

    cliente = ClienteGemini("clave-prueba", transporte=httpx.MockTransport(servidor))
    respuesta = cliente.crear_mensaje(PETICION)
    assert str(peticiones[0].url) == f"{URL_BASE}/gemini-flash-latest:generateContent"
    assert peticiones[0].headers["x-goog-api-key"] == "clave-prueba"
    assert "x-api-key" not in peticiones[0].headers
    assert respuesta.contenido[0]["text"] == "hola"
    assert PARTE_ORIGINAL in respuesta.contenido[0]


def test_cliente_reintenta_429_y_luego_responde() -> None:
    respuestas = [httpx.Response(429), httpx.Response(200, json=gemini({"text": "ok"}))]
    esperas: list[float] = []
    cliente = ClienteGemini(
        "c", transporte=httpx.MockTransport(lambda _p: respuestas.pop(0)), dormir=esperas.append
    )
    assert cliente.crear_mensaje(PETICION).contenido[0]["text"] == "ok"
    assert esperas == [1.0]


def test_cliente_reporta_errores_de_google() -> None:
    cuerpo = {"error": {"status": "INVALID_ARGUMENT", "message": "modelo no existe"}}
    cliente = ClienteGemini(
        "c", transporte=httpx.MockTransport(lambda _p: httpx.Response(400, json=cuerpo))
    )
    with pytest.raises(ErrorClaude, match="INVALID_ARGUMENT: modelo no existe") as error:
        cliente.crear_mensaje(PETICION)
    assert error.value.estado == 400


def configuracion(**valores: str) -> Configuracion:
    datos: dict[str, Any] = {"DATABASE_URL": "postgresql+pg8000://a:b@localhost/c", **valores}
    return Configuracion(_env_file=None, **datos)  # type: ignore[call-arg]


def test_auto_prefiere_claude_si_hay_clave() -> None:
    proveedor = elegir_proveedor(configuracion(ANTHROPIC_API_KEY="a", GEMINI_API_KEY="g"))
    assert proveedor is not None
    assert proveedor.nombre == "claude"
    assert isinstance(proveedor.cliente, ClienteHTTPClaude)


def test_auto_usa_gemini_si_solo_hay_clave_de_google() -> None:
    proveedor = elegir_proveedor(configuracion(ANTHROPIC_API_KEY="", GEMINI_API_KEY="g"))
    assert proveedor is not None
    assert (proveedor.nombre, proveedor.modelo) == ("gemini", "gemini-3.6-flash")


def test_se_puede_forzar_gemini() -> None:
    proveedor = elegir_proveedor(
        configuracion(ANTHROPIC_API_KEY="a", GEMINI_API_KEY="g", PROVEEDOR_IA="gemini")
    )
    assert proveedor is not None and proveedor.nombre == "gemini"


def test_sin_claves_no_hay_proveedor() -> None:
    assert elegir_proveedor(configuracion(ANTHROPIC_API_KEY="", GEMINI_API_KEY="  ")) is None


def test_la_linea_vacia_del_env_cuenta_como_sin_clave() -> None:
    assert configuracion(ANTHROPIC_API_KEY="").anthropic_api_key is None
    assert configuracion(GEMINI_API_KEY="x").gemini_api_key == SecretStr("x")


@pytest.mark.integracion
def test_el_agente_funciona_igual_con_gemini(sesion: Session) -> None:
    guion = [
        gemini(
            {
                "functionCall": {
                    "id": "g1",
                    "name": "buscar_productos",
                    "args": {"categoria": "gorras"},
                },
                "thoughtSignature": "firma-1",
            }
        ),
        gemini({"text": "Hay 2 gorras desde $45.000."}),
    ]
    recibidas: list[dict[str, Any]] = []

    def servidor(peticion: httpx.Request) -> httpx.Response:
        recibidas.append(json.loads(peticion.content))
        return httpx.Response(200, json=guion.pop(0))

    agente = Agente(
        ClienteGemini("c", transporte=httpx.MockTransport(servidor)), modelo="gemini-flash-latest"
    )
    respuesta = agente.responder(sesion, Identidad(Rol.INVITADO), [], "¿qué gorras tienen?")

    assert respuesta.texto == "Hay 2 gorras desde $45.000."
    assert [h.nombre for h in respuesta.herramientas] == ["buscar_productos"]
    segunda = recibidas[1]["contents"]
    assert segunda[1]["parts"][0]["thoughtSignature"] == "firma-1"
    resultado = segunda[2]["parts"][0]["functionResponse"]
    assert resultado["name"] == "buscar_productos"
    assert [p["id"] for p in json.loads(resultado["response"]["resultado"])] == ["p001", "p002"]
