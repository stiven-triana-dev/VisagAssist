"""Tablas de VisagShop que el asistente puede leer.

Se describen solo las columnas que se usan: VisagAssist no crea ni modifica tablas,
la estructura la define y migra VisagShop. Con estas definiciones SQLAlchemy arma las
consultas con parámetros, así nunca se concatena texto del usuario dentro del SQL.
"""

from sqlalchemy import Column, Integer, MetaData, SmallInteger, String, Table, Uuid

metadatos = MetaData()

categorias = Table(
    "categories",
    metadatos,
    Column("id", Integer, primary_key=True),
    Column("name", String(70), nullable=False),
)

tallas = Table(
    "sizes",
    metadatos,
    Column("id", Integer, primary_key=True),
    Column("name", String(25), nullable=False),
)

productos = Table(
    "products",
    metadatos,
    Column("id", String(10), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("description", String(1000), nullable=False),
    Column("price", Integer, nullable=True),
    Column("image", String(200), nullable=False),
    Column("category_id", Integer, nullable=False),
)

productos_tallas = Table(
    "product_sizes",
    metadatos,
    Column("product_id", String(10), primary_key=True),
    Column("size_id", Integer, primary_key=True),
    Column("position", SmallInteger, nullable=False),
)

usuarios = Table(
    "users",
    metadatos,
    Column("id", Uuid, primary_key=True),
    Column("first_name", String(75), nullable=False),
)
