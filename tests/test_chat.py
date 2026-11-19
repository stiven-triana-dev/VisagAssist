import json
from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from conftest import SECRETO_PRUEBAS
from simulado import ClaudeSimulado, herramienta, texto
from visagassist import api
from visagassist.claude import ErrorClaude
from visagassist.historial import conversaciones, mensajes
from visagassist.identidad import Identidad, Rol, emitir_pase

pytestmark = pytest.mark.integracion

ANDRES = Identidad(Rol.CLIENTE, UUID("11111111-1111-4111-8111-111111111111"), "Andrés")
VALENTINA = Identidad(Rol.CLIENTE, UUID("22222222-2222-4222-8222-222222222222"), "Valentina")
PASE_CON_OTRO_SECRETO = emitir_pase(
    Identidad(Rol.ADMINISTRADOR), "otro-secreto-de-al-menos-32-bytes!!"
)


def pase(quien: Identidad, **opciones: timedelta) -> dict[str, str]:
    return {"Authorization": f"Bearer {emitir_pase(quien, SECRETO_PRUEBAS, **opciones)}"}


def preguntar(
    cliente: TestClient, mensaje: str, encabezados: dict[str, str] | None = None, **extra: object
) -> dict[str, object]:
    respuesta = cliente.post(
        "/api/v1/chat", json={"mensaje": mensaje, **extra}, headers=encabezados or {}
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo: dict[str, object] = respuesta.json()
    return cuerpo


def test_un_invitado_pregunta_y_se_guarda_con_su_costo(
    cliente: TestClient, claude: ClaudeSimulado, sesion_asistente: Session
) -> None:
    claude.guion += [herramienta("buscar_productos", {"categoria": "gorras"}), texto("Hay 2.")]
    cuerpo = preguntar(cliente, "  ¿qué   gorras tienen?  ")

    assert cuerpo["respuesta"] == "Hay 2."
    assert cuerpo["herramientas_usadas"] == ["buscar_productos"]
    assert cuerpo["uso"] == {
        "tokens_entrada": 2000,
        "tokens_salida": 200,
        "tokens_cache": 0,
        "costo_usd": 0.0003,
        "rondas": 2,
    }
    conversacion_id = UUID(str(cuerpo["conversacion_id"]))
    filas = sesion_asistente.execute(
        select(mensajes.c.autor, mensajes.c.texto, mensajes.c.costo_usd, mensajes.c.herramientas)
        .where(mensajes.c.conversacion_id == conversacion_id)
        .order_by(mensajes.c.id)
    ).all()
    assert [(f.autor, f.texto) for f in filas] == [
        ("usuario", "¿qué gorras tienen?"),  # espacios normalizados
        ("asistente", "Hay 2."),
    ]
    assert filas[1].costo_usd == Decimal("0.000300")
    assert filas[1].herramientas[0]["nombre"] == "buscar_productos"


def test_seguir_la_conversacion_le_da_contexto_al_modelo(
    cliente: TestClient, claude: ClaudeSimulado
) -> None:
    claude.guion += [texto("La sudadera gris cuesta $185.000."), texto("Sí, hay talla L.")]
    primera = preguntar(cliente, "¿cuánto vale la sudadera gris?")
    preguntar(cliente, "¿y en talla L?", conversacion_id=primera["conversacion_id"])

    assert claude.peticiones[1]["messages"] == [
        {"role": "user", "content": "¿cuánto vale la sudadera gris?"},
        {"role": "assistant", "content": "La sudadera gris cuesta $185.000."},
        {"role": "user", "content": "¿y en talla L?"},
    ]


def test_nadie_puede_continuar_la_conversacion_de_otro(
    cliente: TestClient, claude: ClaudeSimulado
) -> None:
    claude.guion += [texto("Tus pedidos...")]
    de_andres = preguntar(cliente, "mis pedidos", pase(ANDRES))["conversacion_id"]

    for intruso in (pase(VALENTINA), {}):
        respuesta = cliente.post(
            "/api/v1/chat",
            json={"mensaje": "¿qué me dijiste?", "conversacion_id": de_andres},
            headers=intruso,
        )
        assert respuesta.status_code == 404
        assert (
            cliente.get(f"/api/v1/conversaciones/{de_andres}", headers=intruso).status_code == 404
        )


def test_conversacion_inexistente(cliente: TestClient) -> None:
    respuesta = cliente.post(
        "/api/v1/chat", json={"mensaje": "hola", "conversacion_id": str(uuid4())}
    )
    assert respuesta.status_code == 404


def test_el_duenio_puede_leer_su_conversacion(cliente: TestClient, claude: ClaudeSimulado) -> None:
    claude.guion += [texto("¡Hola Andrés!")]
    conversacion_id = preguntar(cliente, "hola", pase(ANDRES))["conversacion_id"]
    lectura = cliente.get(f"/api/v1/conversaciones/{conversacion_id}", headers=pase(ANDRES))
    assert lectura.status_code == 200
    assert [(m["autor"], m["texto"]) for m in lectura.json()] == [
        ("usuario", "hola"),
        ("asistente", "¡Hola Andrés!"),
    ]


def test_un_cliente_con_pase_ve_solo_sus_pedidos(
    cliente: TestClient, claude: ClaudeSimulado
) -> None:
    claude.guion += [herramienta("mis_pedidos"), texto("Tienes 2 pedidos.")]
    preguntar(cliente, "¿cómo van mis pedidos?", pase(VALENTINA))
    pedidos = json.loads(claude.ultimo_mensaje()["content"][0]["content"])
    assert {p["numero"] for p in pedidos} == {"VS-1003", "VS-1004"}


def test_el_administrador_recibe_sus_herramientas(
    cliente: TestClient, claude: ClaudeSimulado
) -> None:
    claude.guion += [texto("ok")]
    preguntar(cliente, "resumen", pase(Identidad(Rol.ADMINISTRADOR)))
    assert "resumen_ventas" in {t["name"] for t in claude.peticiones[0]["tools"]}


@pytest.mark.parametrize(
    "encabezado",
    [
        "Bearer esto-no-es-un-pase",
        "Basic dXN1YXJpbzpjbGF2ZQ==",
        "Bearer",
        f"Bearer {PASE_CON_OTRO_SECRETO}",
    ],
)
def test_pase_invalido_da_401(cliente: TestClient, encabezado: str) -> None:
    respuesta = cliente.post(
        "/api/v1/chat", json={"mensaje": "hola"}, headers={"Authorization": encabezado}
    )
    assert respuesta.status_code == 401


def test_pase_vencido_da_401(cliente: TestClient) -> None:
    vencido = pase(Identidad(Rol.ADMINISTRADOR), vigencia=timedelta(seconds=-30))
    assert (
        cliente.post("/api/v1/chat", json={"mensaje": "hola"}, headers=vencido).status_code == 401
    )


@pytest.mark.parametrize("mensaje", ["", "   ", "x" * 501])
def test_mensajes_invalidos_dan_422(cliente: TestClient, mensaje: str) -> None:
    assert cliente.post("/api/v1/chat", json={"mensaje": mensaje}).status_code == 422


def test_si_claude_falla_responde_502_y_no_deja_basura(
    cliente: TestClient, claude: ClaudeSimulado, sesion_asistente: Session
) -> None:
    antes = sesion_asistente.scalar(select(func.count()).select_from(conversaciones))
    claude.guion += [ErrorClaude("overloaded_error: sobrecargado", 529)]
    respuesta = cliente.post("/api/v1/chat", json={"mensaje": "hola"})
    assert respuesta.status_code == 502
    assert "no está disponible" in respuesta.json()["detail"]
    assert sesion_asistente.scalar(select(func.count()).select_from(conversaciones)) == antes


def test_sin_clave_de_la_api_responde_503(cliente: TestClient) -> None:
    del api.app.dependency_overrides[api.obtener_agente]
    api._agente_configurado.cache_clear()
    respuesta = cliente.post("/api/v1/chat", json={"mensaje": "hola"})
    assert respuesta.status_code == 503
    assert "no está configurado" in respuesta.json()["detail"]
