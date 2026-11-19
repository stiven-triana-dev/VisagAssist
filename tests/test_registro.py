from visagassist.herramientas.registro import HERRAMIENTAS, herramientas_para
from visagassist.identidad import Rol


def nombres(rol: Rol) -> set[str]:
    return {h.nombre for h in herramientas_para(rol)}


def test_invitado_solo_ve_el_catalogo() -> None:
    assert nombres(Rol.INVITADO) == {"buscar_productos", "ver_producto", "listar_categorias"}


def test_cliente_ve_catalogo_y_sus_pedidos() -> None:
    assert nombres(Rol.CLIENTE) == nombres(Rol.INVITADO) | {"mis_pedidos"}


def test_administrador_ve_catalogo_y_herramientas_de_gestion() -> None:
    assert nombres(Rol.ADMINISTRADOR) == nombres(Rol.INVITADO) | {
        "pedidos_pendientes",
        "resumen_ventas",
        "productos_incompletos",
    }


def test_definiciones_en_formato_de_la_api() -> None:
    for herramienta in HERRAMIENTAS:
        definicion = herramienta.definicion_api()
        assert set(definicion) == {"name", "description", "input_schema"}
        esquema = definicion["input_schema"]
        assert esquema["type"] == "object"
        assert esquema["additionalProperties"] is False
        assert "title" not in esquema
        assert len(definicion["description"]) > 30


def test_mis_pedidos_no_tiene_argumento_de_usuario() -> None:
    mis_pedidos = next(h for h in HERRAMIENTAS if h.nombre == "mis_pedidos")
    propiedades = mis_pedidos.definicion_api()["input_schema"]["properties"]
    assert set(propiedades) == {"numero", "limite"}


def test_nombres_unicos() -> None:
    assert len({h.nombre for h in HERRAMIENTAS}) == len(HERRAMIENTAS)
