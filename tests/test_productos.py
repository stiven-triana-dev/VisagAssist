"""Herramienta buscar_productos contra PostgreSQL real (datos de tests/datos/datos_prueba.sql)."""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from visagassist.herramientas.productos import FiltrosBusqueda, buscar_productos

pytestmark = pytest.mark.integracion


def ids(sesion: Session, **filtros: object) -> list[str]:
    return [p.id for p in buscar_productos(sesion, FiltrosBusqueda(**filtros))]  # type: ignore[arg-type]


def test_sin_filtros_ordena_por_precio_y_deja_sin_precio_al_final(sesion: Session) -> None:
    resultado = ids(sesion, limite=20)
    assert resultado[0] == "p001"  # la más barata: 45.000
    assert resultado[-1] == "p008"  # sin precio va al final
    assert len(resultado) == 8


def test_respeta_el_limite(sesion: Session) -> None:
    assert len(ids(sesion, limite=3)) == 3


def test_busca_sin_importar_tildes_ni_mayusculas(sesion: Session) -> None:
    assert ids(sesion, texto="SUDADERA BASICA") == ["p005"]
    assert ids(sesion, texto="básica") == ["p005"]


def test_todas_las_palabras_deben_coincidir(sesion: Session) -> None:
    assert ids(sesion, texto="jean negro") == ["p004"]


def test_busca_tambien_en_la_categoria(sesion: Session) -> None:
    assert ids(sesion, texto="zapatos") == ["p007", "p008"]


def test_filtra_por_categoria(sesion: Session) -> None:
    assert ids(sesion, categoria="gorras") == ["p001", "p002"]


def test_filtra_por_talla_disponible(sesion: Session) -> None:
    assert ids(sesion, talla="32") == ["p004", "p003"]
    assert ids(sesion, talla="xl") == ["p005"]


def test_filtra_por_precio_maximo(sesion: Session) -> None:
    assert ids(sesion, precio_maximo=60000) == ["p001", "p002"]


def test_combina_filtros(sesion: Session) -> None:
    assert ids(sesion, categoria="Sudaderas", talla="M", precio_maximo=182000) == ["p006"]


def test_devuelve_tallas_en_orden_y_lista_vacia_si_no_tiene(sesion: Session) -> None:
    productos = {p.id: p for p in buscar_productos(sesion, FiltrosBusqueda(limite=20))}
    assert productos["p003"].tallas == ["30", "32", "34"]
    assert productos["p008"].tallas == []
    assert productos["p008"].precio is None


def test_arma_el_enlace_al_producto_en_la_tienda(sesion: Session) -> None:
    producto = buscar_productos(sesion, FiltrosBusqueda(texto="gorra roja"))[0]
    assert producto.url == "https://visagshop.onrender.com/productDetail?id=p002"
    assert producto.categoria == "Gorras"
    assert producto.precio == 52000


def test_sin_resultados_devuelve_lista_vacia(sesion: Session) -> None:
    assert ids(sesion, texto="bicicleta") == []


def test_el_porcentaje_no_funciona_como_comodin(sesion: Session) -> None:
    # "%" se busca como carácter literal: solo p006 lo tiene ("100% algodón"), no todo el catálogo.
    assert ids(sesion, texto="%") == ["p006"]
    assert ids(sesion, texto="100%") == ["p006"]


def test_el_guion_bajo_no_funciona_como_comodin(sesion: Session) -> None:
    assert ids(sesion, texto="_") == []


@pytest.mark.parametrize(
    "ataque",
    [
        "'; DROP TABLE products; --",
        "' OR '1'='1",
        "gorra' UNION SELECT id, password_hash, '', 0, '' FROM users --",
    ],
)
def test_un_intento_de_inyeccion_sql_se_trata_como_texto(sesion: Session, ataque: str) -> None:
    assert ids(sesion, texto=ataque) == []
    assert sesion.execute(text("SELECT count(*) FROM products")).scalar_one() == 8


def test_orden_del_mas_caro_al_mas_barato(sesion: Session) -> None:
    # Los productos sin precio quedan al final también en este orden.
    assert ids(sesion, orden="mas_caro", limite=3) == ["p007", "p005", "p006"]
    assert ids(sesion, categoria="gorras", orden="mas_caro") == ["p002", "p001"]


def test_orden_invalido_se_rechaza() -> None:
    with pytest.raises(ValueError):
        FiltrosBusqueda(orden="al_azar")  # type: ignore[arg-type]


def test_el_plural_encuentra_el_singular(sesion: Session) -> None:
    # Hallado en producción: "jeans" no encontraba "Jean 1.1 · Azul roto".
    assert ids(sesion, texto="jeans") == ["p004", "p003"]
    assert ids(sesion, texto="jeans negros") == ["p004"]
    assert ids(sesion, texto="gorras rojas") == ["p002"]
    assert ids(sesion, texto="sudaderas grises") == ["p005"]


def test_raiz_de_las_palabras() -> None:
    from visagassist.herramientas.productos import _raiz

    assert [_raiz(p) for p in ["jeans", "pantalones", "colores", "tenis", "gorra", "es"]] == [
        "jean",
        "pantalon",
        "color",
        "teni",
        "gorra",
        "es",
    ]
