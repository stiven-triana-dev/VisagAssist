from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from visagassist.herramientas.productos import URL_TIENDA
from visagassist.modelos import (
    categorias,
    colores,
    productos,
    productos_colores,
    productos_tallas,
    tallas,
)


class SinArgumentos(BaseModel):
    """La herramienta no recibe argumentos."""


class Categoria(BaseModel):
    nombre: str
    productos: int
    precio_minimo: int | None
    precio_maximo: int | None


def listar_categorias(sesion: Session, _argumentos: SinArgumentos) -> list[Categoria]:
    consulta = (
        select(
            categorias.c.name,
            func.count(productos.c.id),
            func.min(productos.c.price),
            func.max(productos.c.price),
        )
        .join(productos, productos.c.category_id == categorias.c.id, isouter=True)
        .group_by(categorias.c.id, categorias.c.name)
        .order_by(categorias.c.name)
    )
    return [
        Categoria(nombre=nombre, productos=total, precio_minimo=minimo, precio_maximo=maximo)
        for nombre, total, minimo, maximo in sesion.execute(consulta)
    ]


class ArgumentosProducto(BaseModel):
    producto_id: str = Field(pattern=r"^p\d{3,6}$", description="Id del producto, por ejemplo p042")


class DetalleProducto(BaseModel):
    id: str
    nombre: str
    categoria: str
    precio: int | None
    descripcion: str
    tallas: list[str]
    colores: list[str]
    url: str


class ProductoNoEncontrado(LookupError):
    pass


def ver_producto(sesion: Session, argumentos: ArgumentosProducto) -> DetalleProducto:
    fila = sesion.execute(
        select(
            productos.c.id,
            productos.c.name,
            productos.c.description,
            productos.c.price,
            categorias.c.name.label("categoria"),
        )
        .join(categorias, categorias.c.id == productos.c.category_id)
        .where(productos.c.id == argumentos.producto_id)
    ).first()
    if fila is None:
        raise ProductoNoEncontrado(f"No existe el producto {argumentos.producto_id}")

    lista_tallas = sesion.scalars(
        select(tallas.c.name)
        .join(productos_tallas, productos_tallas.c.size_id == tallas.c.id)
        .where(productos_tallas.c.product_id == fila.id)
        .order_by(productos_tallas.c.position)
    ).all()
    lista_colores = sesion.scalars(
        select(colores.c.name)
        .join(productos_colores, productos_colores.c.color_id == colores.c.id)
        .where(productos_colores.c.product_id == fila.id)
        .order_by(productos_colores.c.position)
    ).all()
    return DetalleProducto(
        id=fila.id,
        nombre=fila.name,
        categoria=fila.categoria,
        precio=fila.price,
        descripcion=fila.description,
        tallas=list(lista_tallas),
        colores=list(lista_colores),
        url=f"{URL_TIENDA}/productDetail?id={fila.id}",
    )
