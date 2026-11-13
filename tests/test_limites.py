"""Límites de uso: preguntas por hora y presupuesto diario (protegen el saldo de la API)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from conftest import SECRETO_PRUEBAS
from simulado import ClaudeSimulado, texto
from visagassist import api
from visagassist.historial import conversaciones, mensajes
from visagassist.identidad import Identidad, Rol, emitir_pase
from visagassist.limites import Limites, huella_origen, inicio_del_dia

pytestmark = pytest.mark.integracion

ANDRES = Identidad(Rol.CLIENTE, UUID("11111111-1111-4111-8111-111111111111"))


@pytest.fixture(autouse=True)
def historial_vacio(sesion_asistente: Session) -> Iterator[None]:
    """Cada prueba de límites empieza sin preguntas ni gasto registrados."""
    sesion_asistente.execute(delete(conversaciones))
    sesion_asistente.commit()
    yield
    sesion_asistente.execute(delete(conversaciones))
    sesion_asistente.commit()


def limites(invitado: int = 100, cliente: int = 100, presupuesto: str = "1000") -> None:
    api.app.dependency_overrides[api.obtener_limites] = lambda: Limites(
        por_hora={Rol.INVITADO: invitado, Rol.CLIENTE: cliente, Rol.ADMINISTRADOR: 100},
        presupuesto_diario_usd=Decimal(presupuesto),
    )


def con_origen(ip: str) -> None:
    api.app.dependency_overrides[api.obtener_origen] = lambda: huella_origen(ip, SECRETO_PRUEBAS)


def preguntar(cliente: TestClient, encabezados: dict[str, str] | None = None) -> int:
    return cliente.post("/api/v1/chat", json={"mensaje": "hola"}, headers=encabezados).status_code


def test_un_invitado_alcanza_su_limite_por_hora(
    cliente: TestClient, claude: ClaudeSimulado
) -> None:
    limites(invitado=2)
    con_origen("200.1.1.1")
    claude.guion += [texto("a"), texto("b")]
    assert preguntar(cliente) == 200
    assert preguntar(cliente) == 200

    respuesta = cliente.post("/api/v1/chat", json={"mensaje": "hola"})
    assert respuesta.status_code == 429
    assert respuesta.headers["Retry-After"] == "3600"
    assert "muchas preguntas" in respuesta.json()["detail"]
    assert len(claude.peticiones) == 2  # la tercera no llegó al modelo: no gastó saldo


def test_otro_invitado_desde_otra_conexion_no_se_ve_afectado(
    cliente: TestClient, claude: ClaudeSimulado
) -> None:
    limites(invitado=1)
    claude.guion += [texto("a"), texto("b")]
    con_origen("200.1.1.1")
    assert preguntar(cliente) == 200
    assert preguntar(cliente) == 429
    con_origen("190.2.2.2")
    assert preguntar(cliente) == 200


def test_un_cliente_se_cuenta_por_su_cuenta_y_no_por_la_conexion(
    cliente: TestClient, claude: ClaudeSimulado
) -> None:
    limites(cliente=1)
    pase = {"Authorization": f"Bearer {emitir_pase(ANDRES, SECRETO_PRUEBAS)}"}
    claude.guion += [texto("a"), texto("b")]
    con_origen("200.1.1.1")
    assert preguntar(cliente, pase) == 200
    con_origen("190.2.2.2")  # cambiar de red no le da más preguntas
    assert preguntar(cliente, pase) == 429
    otra = {
        "Authorization": f"Bearer {emitir_pase(Identidad(Rol.CLIENTE, uuid4()), SECRETO_PRUEBAS)}"
    }
    assert preguntar(cliente, otra) == 200


def test_solo_cuentan_las_preguntas_de_la_ultima_hora(
    cliente: TestClient, claude: ClaudeSimulado, sesion_asistente: Session
) -> None:
    limites(invitado=1)
    con_origen("200.1.1.1")
    huella = huella_origen("200.1.1.1", SECRETO_PRUEBAS)
    conversacion = uuid4()
    sesion_asistente.execute(
        insert(conversaciones).values(id=conversacion, propietario="invitado:-", rol="invitado")
    )
    sesion_asistente.execute(
        insert(mensajes).values(
            conversacion_id=conversacion,
            autor="usuario",
            texto="vieja",
            origen=huella,
            creado_en=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    sesion_asistente.commit()
    claude.guion += [texto("a")]
    assert preguntar(cliente) == 200


def test_presupuesto_diario_agotado_detiene_a_todos(
    cliente: TestClient, claude: ClaudeSimulado, sesion_asistente: Session
) -> None:
    limites(presupuesto="0.50")
    conversacion = uuid4()
    sesion_asistente.execute(
        insert(conversaciones).values(id=conversacion, propietario="x", rol="invitado")
    )
    sesion_asistente.execute(
        insert(mensajes).values(
            conversacion_id=conversacion, autor="asistente", texto="caro", costo_usd=Decimal("0.5")
        )
    )
    sesion_asistente.commit()

    for encabezados in ({}, {"Authorization": f"Bearer {emitir_pase(ANDRES, SECRETO_PRUEBAS)}"}):
        respuesta = cliente.post("/api/v1/chat", json={"mensaje": "hola"}, headers=encabezados)
        assert respuesta.status_code == 429
        assert "límite de uso de hoy" in respuesta.json()["detail"]
        assert 0 < int(respuesta.headers["Retry-After"]) <= 86_400
    assert claude.peticiones == []


def test_el_gasto_de_ayer_no_cuenta_para_hoy(
    cliente: TestClient, claude: ClaudeSimulado, sesion_asistente: Session
) -> None:
    limites(presupuesto="0.50")
    conversacion = uuid4()
    sesion_asistente.execute(
        insert(conversaciones).values(id=conversacion, propietario="x", rol="invitado")
    )
    ayer = inicio_del_dia(datetime.now(UTC)) - timedelta(hours=1)
    sesion_asistente.execute(
        insert(mensajes).values(
            conversacion_id=conversacion,
            autor="asistente",
            texto="caro",
            costo_usd=Decimal("5"),
            creado_en=ayer,
        )
    )
    sesion_asistente.commit()
    claude.guion += [texto("hola")]
    assert preguntar(cliente) == 200


def test_la_huella_no_guarda_la_ip_y_depende_del_secreto() -> None:
    huella = huella_origen("200.1.1.1", "secreto-a")
    assert "200.1.1.1" not in huella
    assert len(huella) == 32
    assert huella == huella_origen("200.1.1.1", "secreto-a")
    assert huella != huella_origen("200.1.1.1", "secreto-b")
    assert huella != huella_origen("200.1.1.2", "secreto-a")


def test_inicio_del_dia_en_hora_de_colombia() -> None:
    # 3 a. m. UTC del 13 de noviembre = 10 p. m. del 12 de noviembre en Colombia.
    momento = datetime(2026, 11, 13, 3, 0, tzinfo=UTC)
    inicio = inicio_del_dia(momento)
    assert (inicio.year, inicio.month, inicio.day, inicio.hour) == (2026, 11, 12, 0)
