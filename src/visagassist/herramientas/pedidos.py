from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session

from visagassist.modelos import items_pedido, pedidos, productos, productos_tallas

ZONA_TIENDA = ZoneInfo("America/Bogota")
Estado = Literal["nuevo", "confirmado", "enviado", "entregado", "cancelado"]


class ItemPedido(BaseModel):
    producto: str
    talla: str
    cantidad: int
    precio_unitario: int | None


class Pedido(BaseModel):
    numero: str = Field(description="Como lo ve el cliente, por ejemplo VS-1001")
    estado: Estado
    fecha: str
    ciudad: str
    total: int
    tiene_productos_sin_precio: bool
    items: list[ItemPedido]


def _fecha_local(momento: datetime) -> str:
    return momento.astimezone(ZONA_TIENDA).strftime("%Y-%m-%d")


def _items(sesion: Session, ids_pedido: list[UUID]) -> dict[UUID, list[ItemPedido]]:
    if not ids_pedido:
        return {}
    consulta = (
        select(
            items_pedido.c.order_id,
            items_pedido.c.product_name,
            items_pedido.c.size,
            items_pedido.c.quantity,
            items_pedido.c.unit_price,
        )
        .where(items_pedido.c.order_id.in_(ids_pedido))
        .order_by(items_pedido.c.order_id, items_pedido.c.position)
    )
    resultado: dict[UUID, list[ItemPedido]] = {}
    for pedido_id, nombre, talla, cantidad, precio in sesion.execute(consulta):
        resultado.setdefault(pedido_id, []).append(
            ItemPedido(producto=nombre, talla=talla, cantidad=cantidad, precio_unitario=precio)
        )
    return resultado


class ArgumentosMisPedidos(BaseModel):
    numero: int | None = Field(
        default=None,
        ge=1000,
        le=9_999_999,
        description="Número del pedido si el cliente pregunta por uno (VS-1001 -> 1001)",
    )
    limite: int = Field(default=5, ge=1, le=10)

    @field_validator("numero", mode="before")
    @classmethod
    def _quitar_prefijo(cls, valor: object) -> object:
        if isinstance(valor, str):
            return valor.upper().removeprefix("VS-").removeprefix("VS").strip() or None
        return valor


def mis_pedidos(
    sesion: Session, argumentos: ArgumentosMisPedidos, usuario_id: UUID
) -> list[Pedido]:
    """Pedidos del cliente. El id viene de la identidad firmada, nunca del modelo de IA."""
    condiciones: list[ColumnElement[bool]] = [pedidos.c.user_id == usuario_id]
    if argumentos.numero is not None:
        condiciones.append(pedidos.c.number == argumentos.numero)
    filas = sesion.execute(
        select(pedidos)
        .where(*condiciones)
        .order_by(pedidos.c.created_at.desc())
        .limit(argumentos.limite)
    ).all()
    items = _items(sesion, [f.id for f in filas])
    return [
        Pedido(
            numero=f"VS-{f.number}",
            estado=f.status,
            fecha=_fecha_local(f.created_at),
            ciudad=f.city,
            total=f.subtotal,
            tiene_productos_sin_precio=f.has_unpriced,
            items=items.get(f.id, []),
        )
        for f in filas
    ]


class ArgumentosPendientes(BaseModel):
    limite: int = Field(default=10, ge=1, le=30)


class PedidoPendiente(BaseModel):
    numero: str
    estado: Estado
    fecha: str
    dias_esperando: int
    cliente: str = Field(description="Nombre e inicial del apellido (sin datos de contacto)")
    ciudad: str
    total: int
    unidades: int
    medio_de_pago: str


def pedidos_pendientes(sesion: Session, argumentos: ArgumentosPendientes) -> list[PedidoPendiente]:
    unidades = (
        select(func.coalesce(func.sum(items_pedido.c.quantity), 0))
        .where(items_pedido.c.order_id == pedidos.c.id)
        .scalar_subquery()
    )
    filas = sesion.execute(
        select(pedidos, unidades.label("unidades"))
        .where(pedidos.c.status.in_(["nuevo", "confirmado"]))
        .order_by(pedidos.c.created_at.asc())
        .limit(argumentos.limite)
    ).all()
    ahora = datetime.now(UTC)
    return [
        PedidoPendiente(
            numero=f"VS-{f.number}",
            estado=f.status,
            fecha=_fecha_local(f.created_at),
            dias_esperando=(ahora - f.created_at).days,
            cliente=f"{f.first_name} {f.last_name[:1]}.".strip(),
            ciudad=f.city,
            total=f.subtotal,
            unidades=int(f.unidades),
            medio_de_pago=f.payment_method,
        )
        for f in filas
    ]


class ArgumentosResumen(BaseModel):
    dias: int = Field(default=30, ge=1, le=365, description="Últimos N días (1 a 365)")


class ProductoVendido(BaseModel):
    producto: str
    unidades: int


class ResumenVentas(BaseModel):
    desde: str
    hasta: str
    pedidos: int
    pedidos_por_estado: dict[str, int]
    total_vendido: int = Field(description="Suma de pedidos no cancelados, en pesos")
    ticket_promedio: int
    mas_vendidos: list[ProductoVendido]


def resumen_ventas(sesion: Session, argumentos: ArgumentosResumen) -> ResumenVentas:
    ahora = datetime.now(UTC)
    desde = ahora - timedelta(days=argumentos.dias)
    en_rango = pedidos.c.created_at >= desde
    no_cancelado = pedidos.c.status != "cancelado"

    por_estado: dict[str, int] = dict(
        sesion.execute(
            select(pedidos.c.status, func.count()).where(en_rango).group_by(pedidos.c.status)
        ).all()
    )
    vendidos, total = sesion.execute(
        select(func.count(), func.coalesce(func.sum(pedidos.c.subtotal), 0)).where(
            en_rango, no_cancelado
        )
    ).one()
    top = sesion.execute(
        select(items_pedido.c.product_name, func.sum(items_pedido.c.quantity).label("u"))
        .join(pedidos, pedidos.c.id == items_pedido.c.order_id)
        .where(en_rango, no_cancelado)
        .group_by(items_pedido.c.product_name)
        .order_by(func.sum(items_pedido.c.quantity).desc(), items_pedido.c.product_name)
        .limit(5)
    ).all()
    return ResumenVentas(
        desde=_fecha_local(desde),
        hasta=_fecha_local(ahora),
        pedidos=sum(por_estado.values()),
        pedidos_por_estado={str(k): int(v) for k, v in por_estado.items()},
        total_vendido=int(total),
        ticket_promedio=int(total) // vendidos if vendidos else 0,
        mas_vendidos=[ProductoVendido(producto=n, unidades=int(u)) for n, u in top],
    )


class ArgumentosIncompletos(BaseModel):
    limite: int = Field(default=20, ge=1, le=50)


class ProductoIncompleto(BaseModel):
    id: str
    nombre: str
    falta: list[str]


def productos_incompletos(
    sesion: Session, argumentos: ArgumentosIncompletos
) -> list[ProductoIncompleto]:
    sin_tallas = ~(
        select(productos_tallas.c.product_id)
        .where(productos_tallas.c.product_id == productos.c.id)
        .exists()
    )
    filas = sesion.execute(
        select(
            productos.c.id,
            productos.c.name,
            case((sin_tallas, True), else_=False).label("sin_tallas"),
            (productos.c.price.is_(None)).label("sin_precio"),
        )
        .where(sin_tallas | productos.c.price.is_(None))
        .order_by(productos.c.id)
        .limit(argumentos.limite)
    ).all()
    return [
        ProductoIncompleto(
            id=f.id,
            nombre=f.name,
            falta=[x for x, falta in (("tallas", f.sin_tallas), ("precio", f.sin_precio)) if falta],
        )
        for f in filas
    ]
