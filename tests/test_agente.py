import json
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from simulado import ClaudeSimulado, herramienta, rechazo, texto, varias
from visagassist.agente import (
    MENSAJE_LIMITE,
    MENSAJE_RECHAZO,
    MENSAJE_SIN_RESPUESTA,
    Agente,
    Turno,
)
from visagassist.claude import RespuestaClaude, Uso
from visagassist.identidad import Identidad, Rol

pytestmark = pytest.mark.integracion

INVITADO = Identidad(Rol.INVITADO)
ANDRES = Identidad(Rol.CLIENTE, UUID("11111111-1111-4111-8111-111111111111"))
ADMIN = Identidad(Rol.ADMINISTRADOR)


def test_responde_sin_herramientas_en_una_ronda(sesion: Session) -> None:
    claude = ClaudeSimulado(texto("¡Hola! ¿Qué buscas hoy?"))
    respuesta = Agente(claude).responder(sesion, INVITADO, [], "hola")
    assert respuesta.texto == "¡Hola! ¿Qué buscas hoy?"
    assert respuesta.motivo == "end_turn"
    assert respuesta.rondas == 1
    assert respuesta.herramientas == []


def test_usa_una_herramienta_y_le_devuelve_datos_reales_a_claude(sesion: Session) -> None:
    claude = ClaudeSimulado(
        herramienta("buscar_productos", {"categoria": "gorras"}),
        texto("Tenemos 2 gorras desde $45.000."),
    )
    respuesta = Agente(claude).responder(sesion, INVITADO, [], "¿qué gorras tienen?")

    resultado = claude.ultimo_mensaje()["content"][0]
    assert resultado["type"] == "tool_result"
    assert resultado["tool_use_id"] == "toolu_1"
    assert "is_error" not in resultado
    assert [p["id"] for p in json.loads(resultado["content"])] == ["p001", "p002"]
    assert respuesta.texto == "Tenemos 2 gorras desde $45.000."
    assert [h.nombre for h in respuesta.herramientas] == ["buscar_productos"]
    assert respuesta.rondas == 2


def test_varias_herramientas_a_la_vez_van_en_un_solo_mensaje(sesion: Session) -> None:
    claude = ClaudeSimulado(
        varias(
            {
                "type": "tool_use",
                "id": "a",
                "name": "ver_producto",
                "input": {"producto_id": "p001"},
            },
            {
                "type": "tool_use",
                "id": "b",
                "name": "ver_producto",
                "input": {"producto_id": "p005"},
            },
        ),
        texto("Listo."),
    )
    Agente(claude).responder(sesion, INVITADO, [], "compara p001 y p005")
    resultados = claude.ultimo_mensaje()["content"]
    assert [r["tool_use_id"] for r in resultados] == ["a", "b"]
    assert json.loads(resultados[1]["content"])["nombre"] == "Sudadera básica · Gris"


def test_un_error_de_herramienta_se_le_informa_a_claude_y_sigue(sesion: Session) -> None:
    claude = ClaudeSimulado(
        herramienta("ver_producto", {"producto_id": "p999"}),
        texto("Ese producto no existe."),
    )
    respuesta = Agente(claude).responder(sesion, INVITADO, [], "¿y el p999?")
    resultado = claude.ultimo_mensaje()["content"][0]
    assert resultado["is_error"] is True
    assert "No existe el producto p999" in resultado["content"]
    assert respuesta.herramientas[0].es_error
    assert respuesta.texto == "Ese producto no existe."


def test_si_claude_pide_una_herramienta_de_admin_siendo_cliente_se_rechaza(sesion: Session) -> None:
    claude = ClaudeSimulado(herramienta("resumen_ventas", {"dias": 30}), texto("No puedo."))
    Agente(claude).responder(sesion, ANDRES, [], "dame las ventas del mes")
    resultado = claude.ultimo_mensaje()["content"][0]
    assert resultado["is_error"] is True
    assert "No tienes permiso" in resultado["content"]
    assert "total_vendido" not in resultado["content"]


def test_el_cliente_recibe_solo_sus_pedidos(sesion: Session) -> None:
    claude = ClaudeSimulado(herramienta("mis_pedidos"), texto("Tienes 2 pedidos."))
    Agente(claude).responder(sesion, ANDRES, [], "¿cómo van mis pedidos?")
    pedidos = json.loads(claude.ultimo_mensaje()["content"][0]["content"])
    assert {p["numero"] for p in pedidos} == {"VS-1001", "VS-1002"}


def test_rechazo_del_modelo_da_un_mensaje_amable(sesion: Session) -> None:
    respuesta = Agente(ClaudeSimulado(rechazo())).responder(sesion, INVITADO, [], "algo prohibido")
    assert respuesta.texto == MENSAJE_RECHAZO
    assert respuesta.motivo == "refusal"


def test_respuesta_vacia(sesion: Session) -> None:
    respuesta = Agente(ClaudeSimulado(texto(""))).responder(sesion, INVITADO, [], "...")
    assert respuesta.texto == MENSAJE_SIN_RESPUESTA


def test_tope_de_rondas_evita_ciclos_infinitos(sesion: Session) -> None:
    claude = ClaudeSimulado(*(herramienta("listar_categorias", id_=f"t{i}") for i in range(3)))
    respuesta = Agente(claude, maximo_rondas=3).responder(sesion, INVITADO, [], "?")
    assert respuesta.motivo == "limite_rondas"
    assert respuesta.texto == MENSAJE_LIMITE
    assert len(claude.peticiones) == 3


def test_suma_el_uso_de_todas_las_rondas_y_calcula_el_costo(sesion: Session) -> None:
    claude = ClaudeSimulado(
        herramienta("listar_categorias", uso=Uso(entrada=2000, salida=50, cache_lectura=1000)),
        texto("Hay 4 categorías.", uso=Uso(entrada=2500, salida=80, cache_lectura=1000)),
    )
    respuesta = Agente(claude).responder(sesion, INVITADO, [], "¿qué venden?")
    assert respuesta.uso == Uso(entrada=4500, salida=130, cache_lectura=2000)
    assert respuesta.costo_usd == Decimal("0.000535")


def test_conserva_los_bloques_de_razonamiento_tal_como_llegan(sesion: Session) -> None:
    pensando = {"type": "thinking", "thinking": "", "signature": "firma-opaca"}
    uso_herramienta = {"type": "tool_use", "id": "x", "name": "listar_categorias", "input": {}}
    claude = ClaudeSimulado(
        RespuestaClaude([pensando, uso_herramienta], "tool_use", Uso(), "claude-haiku-5-5"),
        texto("ok"),
    )
    Agente(claude).responder(sesion, INVITADO, [], "?")
    asistente = claude.peticiones[1]["messages"][-2]
    assert asistente == {"role": "assistant", "content": [pensando, uso_herramienta]}


def test_forma_de_la_peticion(sesion: Session) -> None:
    claude = ClaudeSimulado(texto("ok"))
    Agente(claude, modelo="claude-haiku-5-5").responder(sesion, ADMIN, [], "resumen")
    peticion = claude.peticiones[0]
    assert peticion["model"] == "claude-haiku-5-5"
    assert peticion["cache_control"] == {"type": "ephemeral"}
    assert peticion["output_config"] == {"effort": "low"}
    assert "temperature" not in peticion  # la versión 2026-10-21 de la API la rechaza
    assert "administrador" in peticion["system"][0]["text"]
    assert {t["name"] for t in peticion["tools"]} >= {"resumen_ventas", "pedidos_pendientes"}


def test_el_invitado_no_recibe_herramientas_privadas(sesion: Session) -> None:
    claude = ClaudeSimulado(texto("ok"))
    Agente(claude).responder(sesion, INVITADO, [], "hola")
    nombres = {t["name"] for t in claude.peticiones[0]["tools"]}
    assert nombres == {"buscar_productos", "ver_producto", "listar_categorias"}


def test_incluye_el_historial_de_la_conversacion(sesion: Session) -> None:
    claude = ClaudeSimulado(texto("La talla L sí está."))
    historial = [
        Turno("usuario", "¿tienen la sudadera gris?"),
        Turno("asistente", "Sí, la p005 a $185.000."),
    ]
    Agente(claude).responder(sesion, INVITADO, historial, "¿y en talla L?")
    assert claude.peticiones[0]["messages"] == [
        {"role": "user", "content": "¿tienen la sudadera gris?"},
        {"role": "assistant", "content": "Sí, la p005 a $185.000."},
        {"role": "user", "content": "¿y en talla L?"},
    ]


def test_las_instrucciones_son_estables_para_aprovechar_la_cache(sesion: Session) -> None:
    claude = ClaudeSimulado(texto("a"), texto("b"))
    agente = Agente(claude)
    agente.responder(sesion, ANDRES, [], "uno")
    agente.responder(sesion, ANDRES, [], "dos")
    primera, segunda = claude.peticiones
    assert primera["system"] == segunda["system"]
    assert primera["tools"] == segunda["tools"]
