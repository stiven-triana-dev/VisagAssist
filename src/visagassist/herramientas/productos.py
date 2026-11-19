from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.orm import Session

from visagassist.modelos import categorias, productos, productos_tallas, tallas

URL_TIENDA = "https://visagshop.onrender.com"

_CON_TILDE = "áéíóúüñ"
_SIN_TILDE = "aeiouun"


def _normalizar(texto: str) -> str:
    return texto.lower().translate(str.maketrans(_CON_TILDE, _SIN_TILDE)).strip()


def _columna_normalizada(columna: ColumnElement[str]) -> ColumnElement[str]:
    return func.translate(func.lower(columna), _CON_TILDE, _SIN_TILDE)


def _raiz(palabra: str) -> str:
    if len(palabra) > 4 and palabra.endswith("es") and palabra[-3] not in "aeiou":
        return palabra[:-2]
    if len(palabra) > 3 and palabra.endswith("s"):
        return palabra[:-1]
    return palabra


class FiltrosBusqueda(BaseModel):
    """Argumentos que el modelo puede pasar a la herramienta (validados antes de consultar)."""

    texto: str | None = Field(default=None, max_length=80, description="Palabras a buscar")
    categoria: str | None = Field(default=None, max_length=70)
    talla: str | None = Field(default=None, max_length=25)
    precio_maximo: int | None = Field(default=None, ge=0, le=10_000_000)
    limite: int = Field(default=10, ge=1, le=20)
    orden: Literal["mas_barato", "mas_caro"] = Field(
        default="mas_barato",
        description="mas_caro para encontrar los productos de mayor precio primero",
    )


class ProductoResumen(BaseModel):
    id: str
    nombre: str
    categoria: str
    precio: int | None = Field(description="Precio en pesos colombianos; None si no tiene precio")
    tallas: list[str]
    descripcion: str
    url: str


def buscar_productos(sesion: Session, filtros: FiltrosBusqueda) -> list[ProductoResumen]:
    condiciones: list[ColumnElement[bool]] = []

    if filtros.texto:
        for palabra in map(_raiz, _normalizar(filtros.texto).split()[:6]):
            condiciones.append(
                or_(
                    _columna_normalizada(productos.c.name).contains(palabra, autoescape=True),
                    _columna_normalizada(productos.c.description).contains(
                        palabra, autoescape=True
                    ),
                    _columna_normalizada(categorias.c.name).contains(palabra, autoescape=True),
                )
            )
    if filtros.categoria:
        condiciones.append(
            _columna_normalizada(categorias.c.name) == _normalizar(filtros.categoria)
        )
    if filtros.talla:
        condiciones.append(
            exists(
                select(productos_tallas.c.product_id)
                .join(tallas, tallas.c.id == productos_tallas.c.size_id)
                .where(
                    productos_tallas.c.product_id == productos.c.id,
                    func.lower(tallas.c.name) == filtros.talla.strip().lower(),
                )
            )
        )
    if filtros.precio_maximo is not None:
        condiciones.append(productos.c.price <= filtros.precio_maximo)

    consulta = (
        select(
            productos.c.id,
            productos.c.name,
            productos.c.description,
            productos.c.price,
            categorias.c.name.label("categoria"),
        )
        .join(categorias, categorias.c.id == productos.c.category_id)
        .where(*condiciones)
        .order_by(
            productos.c.price.desc().nulls_last()
            if filtros.orden == "mas_caro"
            else productos.c.price.asc().nulls_last(),
            productos.c.id,
        )
        .limit(filtros.limite)
    )
    filas = sesion.execute(consulta).all()
    tallas_por_producto = _tallas_de(sesion, [fila.id for fila in filas])

    return [
        ProductoResumen(
            id=fila.id,
            nombre=fila.name,
            categoria=fila.categoria,
            precio=fila.price,
            tallas=tallas_por_producto.get(fila.id, []),
            descripcion=fila.description[:240],
            url=f"{URL_TIENDA}/productDetail?id={fila.id}",
        )
        for fila in filas
    ]


def _tallas_de(sesion: Session, ids: list[str]) -> dict[str, list[str]]:
    if not ids:
        return {}
    consulta = (
        select(productos_tallas.c.product_id, tallas.c.name)
        .join(tallas, tallas.c.id == productos_tallas.c.size_id)
        .where(productos_tallas.c.product_id.in_(ids))
        .order_by(productos_tallas.c.product_id, productos_tallas.c.position)
    )
    resultado: dict[str, list[str]] = {}
    for producto_id, talla in sesion.execute(consulta):
        resultado.setdefault(producto_id, []).append(talla)
    return resultado
