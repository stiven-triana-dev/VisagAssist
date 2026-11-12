"""Herramientas de catálogo, pedidos y administrador, y su registro con permisos por rol."""

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from visagassist.herramientas import registro
from visagassist.identidad import Identidad, Rol

pytestmark = pytest.mark.integracion

ANDRES = Identidad(Rol.CLIENTE, UUID("11111111-1111-4111-8111-111111111111"), "Andrés")
VALENTINA = Identidad(Rol.CLIENTE, UUID("22222222-2222-4222-8222-222222222222"), "Valentina")
ADMIN = Identidad(Rol.ADMINISTRADOR)
INVITADO = Identidad(Rol.INVITADO)


def correr(sesion: Session, nombre: str, quien: Identidad, **entrada: object) -> Any:
    resultado = registro.ejecutar(sesion, nombre, entrada, quien)
    assert not resultado.es_error, resultado.contenido
    return json.loads(resultado.contenido)


def error(sesion: Session, nombre: str, quien: Identidad, **entrada: object) -> str:
    resultado = registro.ejecutar(sesion, nombre, entrada, quien)
    assert resultado.es_error
    return resultado.contenido


# ------------------------------------------------------------------ catálogo


def test_listar_categorias_con_conteo_y_rango_de_precios(sesion: Session) -> None:
    categorias = {c["nombre"]: c for c in correr(sesion, "listar_categorias", INVITADO)}
    assert categorias["Gorras"] == {
        "nombre": "Gorras",
        "productos": 2,
        "precio_minimo": 45000,
        "precio_maximo": 52000,
    }
    assert categorias["Zapatos"]["precio_maximo"] == 260000


def test_ver_producto_con_tallas_y_colores(sesion: Session) -> None:
    producto = correr(sesion, "ver_producto", INVITADO, producto_id="p005")
    assert producto == {
        "id": "p005",
        "nombre": "Sudadera básica · Gris",
        "categoria": "Sudaderas",
        "precio": 185000,
        "descripcion": "Sudadera de algodón con capucha, gris.",
        "tallas": ["M", "L", "XL"],
        "colores": ["Gris"],
        "url": "https://visagshop.onrender.com/productDetail?id=p005",
    }


def test_ver_producto_inexistente_es_error_claro(sesion: Session) -> None:
    assert "No existe el producto p999" in error(
        sesion, "ver_producto", INVITADO, producto_id="p999"
    )


def test_ver_producto_rechaza_ids_con_formato_raro(sesion: Session) -> None:
    assert "Argumentos no válidos" in error(
        sesion, "ver_producto", INVITADO, producto_id="p001' OR '1'='1"
    )


# ------------------------------------------------------------------ pedidos del cliente


def test_un_cliente_ve_solo_sus_pedidos_del_mas_reciente_al_mas_antiguo(sesion: Session) -> None:
    pedidos = correr(sesion, "mis_pedidos", ANDRES)
    assert [p["numero"] for p in pedidos] == ["VS-1002", "VS-1001"]
    assert pedidos[0]["estado"] == "enviado"
    assert pedidos[0]["total"] == 97000
    assert [i["producto"] for i in pedidos[0]["items"]] == [
        "Gorra curva · Negra",
        "Gorra plana · Roja",
    ]


def test_otra_clienta_no_ve_los_pedidos_de_andres(sesion: Session) -> None:
    pedidos = correr(sesion, "mis_pedidos", VALENTINA)
    assert {p["numero"] for p in pedidos} == {"VS-1003", "VS-1004"}


@pytest.mark.parametrize("numero", [1001, "1001", "VS-1001", "vs-1001"])
def test_buscar_un_pedido_por_numero(sesion: Session, numero: object) -> None:
    pedidos = correr(sesion, "mis_pedidos", ANDRES, numero=numero)
    assert [p["numero"] for p in pedidos] == ["VS-1001"]


def test_pedir_el_numero_de_otro_cliente_no_devuelve_nada(sesion: Session) -> None:
    assert correr(sesion, "mis_pedidos", ANDRES, numero=1003) == []


def test_el_modelo_no_puede_cambiar_el_usuario_con_argumentos_extra(sesion: Session) -> None:
    # Aunque el modelo intente mandar un user_id, la herramienta solo usa la identidad firmada.
    resultado = registro.ejecutar(
        sesion, "mis_pedidos", {"user_id": str(VALENTINA.usuario_id)}, ANDRES
    )
    pedidos = json.loads(resultado.contenido)
    assert {p["numero"] for p in pedidos} == {"VS-1001", "VS-1002"}


def test_el_pedido_no_expone_datos_de_contacto(sesion: Session) -> None:
    texto = registro.ejecutar(sesion, "mis_pedidos", {}, ANDRES).contenido
    for dato_privado in ("3000000001", "1000000001", "Calle secreta", "andres@prueba.test"):
        assert dato_privado not in texto


def test_cliente_sin_pedidos(sesion: Session) -> None:
    assert correr(sesion, "mis_pedidos", Identidad(Rol.CLIENTE, uuid4())) == []


# ------------------------------------------------------------------ administrador


def test_pedidos_pendientes_del_mas_antiguo_al_mas_reciente(sesion: Session) -> None:
    pendientes = correr(sesion, "pedidos_pendientes", ADMIN)
    assert [p["numero"] for p in pendientes] == ["VS-1003", "VS-1005"]
    primero = pendientes[0]
    assert primero["cliente"] == "Valentina R."
    assert primero["unidades"] == 2
    assert primero["dias_esperando"] == 2


def test_pendientes_no_expone_contacto(sesion: Session) -> None:
    texto = registro.ejecutar(sesion, "pedidos_pendientes", {}, ADMIN).contenido
    assert "3000000002" not in texto
    assert "Calle secreta" not in texto


def test_resumen_de_ventas_de_30_dias(sesion: Session) -> None:
    resumen = correr(sesion, "resumen_ventas", ADMIN, dias=30)
    assert resumen["pedidos"] == 4  # el de hace 40 días queda fuera
    assert resumen["pedidos_por_estado"] == {
        "enviado": 1,
        "nuevo": 1,
        "cancelado": 1,
        "confirmado": 1,
    }
    assert resumen["total_vendido"] == 97000 + 370000 + 140000  # sin el cancelado
    assert resumen["ticket_promedio"] == 607000 // 3
    assert resumen["mas_vendidos"][0] == {"producto": "Sudadera básica · Gris", "unidades": 2}


def test_resumen_de_ventas_de_un_ano_incluye_el_pedido_antiguo(sesion: Session) -> None:
    assert correr(sesion, "resumen_ventas", ADMIN, dias=365)["pedidos"] == 5


def test_resumen_rechaza_rangos_absurdos(sesion: Session) -> None:
    assert "Argumentos no válidos" in error(sesion, "resumen_ventas", ADMIN, dias=5000)


def test_productos_incompletos(sesion: Session) -> None:
    assert correr(sesion, "productos_incompletos", ADMIN) == [
        {"id": "p008", "nombre": "Tenis clásicos · Negros", "falta": ["tallas", "precio"]}
    ]


# ------------------------------------------------------------------ permisos por rol


@pytest.mark.parametrize(
    "herramienta", ["pedidos_pendientes", "resumen_ventas", "productos_incompletos"]
)
@pytest.mark.parametrize("quien", [INVITADO, ANDRES])
def test_herramientas_de_admin_rechazadas_para_otros_roles(
    sesion: Session, herramienta: str, quien: Identidad
) -> None:
    assert "No tienes permiso" in error(sesion, herramienta, quien)


@pytest.mark.parametrize("quien", [INVITADO, ADMIN])
def test_mis_pedidos_solo_para_clientes(sesion: Session, quien: Identidad) -> None:
    assert "No tienes permiso" in error(sesion, "mis_pedidos", quien)


def test_herramienta_inexistente(sesion: Session) -> None:
    assert "no existe" in error(sesion, "ejecutar_sql", ADMIN, consulta="DROP TABLE products")
