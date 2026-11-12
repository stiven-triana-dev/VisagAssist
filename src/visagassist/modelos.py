"""Tablas de VisagShop que el asistente puede leer.

Se describen solo las columnas que se usan: VisagAssist no crea ni modifica tablas,
la estructura la define y migra VisagShop. Con estas definiciones SQLAlchemy arma las
consultas con parámetros, así nunca se concatena texto del usuario dentro del SQL.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Uuid,
)

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

colores = Table(
    "colors",
    metadatos,
    Column("id", Integer, primary_key=True),
    Column("name", String(25), nullable=False),
)

productos_colores = Table(
    "product_colors",
    metadatos,
    Column("product_id", String(10), primary_key=True),
    Column("color_id", Integer, primary_key=True),
    Column("position", SmallInteger, nullable=False),
)

# Pedidos: solo las columnas que el asistente necesita. Teléfono, dirección y documento
# del cliente NO se describen aquí, así ninguna herramienta puede leerlos por error.
pedidos = Table(
    "orders",
    metadatos,
    Column("id", Uuid, primary_key=True),
    Column("number", Integer, nullable=False),
    Column("user_id", Uuid, nullable=True),
    Column("status", String(20), nullable=False),
    Column("first_name", String(65), nullable=False),
    Column("last_name", String(65), nullable=False),
    Column("city", String(70), nullable=False),
    Column("payment_method", String(20), nullable=False),
    Column("subtotal", Integer, nullable=False),
    Column("has_unpriced", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

items_pedido = Table(
    "order_items",
    metadatos,
    Column("id", Integer, primary_key=True),
    Column("order_id", Uuid, nullable=False),
    Column("product_id", String(10), nullable=True),
    Column("product_name", String(120), nullable=False),
    Column("size", String(50), nullable=False),
    Column("quantity", SmallInteger, nullable=False),
    Column("unit_price", Integer, nullable=True),
    Column("position", SmallInteger, nullable=False),
)
