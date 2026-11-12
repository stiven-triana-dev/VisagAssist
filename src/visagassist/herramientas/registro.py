"""Lista cerrada de herramientas, con los roles que pueden usar cada una.

El modelo de IA solo ve las herramientas de su rol. Aun así, al ejecutar se vuelve a
revisar el permiso (defensa en profundidad): si por un error o un truco el modelo pidiera
una herramienta de administrador siendo cliente, se rechaza.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from visagassist.herramientas import catalogo, pedidos, productos
from visagassist.identidad import Identidad, Rol

registro_log = logging.getLogger(__name__)

TODOS = frozenset(Rol)
SOLO_CLIENTE = frozenset({Rol.CLIENTE})
SOLO_ADMIN = frozenset({Rol.ADMINISTRADOR})
MAXIMO_CARACTERES_RESULTADO = 12_000

Resultado = BaseModel | list[Any]
Ejecutor = Callable[[Session, Any, Identidad], Resultado]


@dataclass(frozen=True)
class Herramienta:
    nombre: str
    descripcion: str
    argumentos: type[BaseModel]
    roles: frozenset[Rol]
    ejecutar: Ejecutor

    def definicion_api(self) -> dict[str, Any]:
        """Definición en el formato de la API de Claude (name, description, input_schema)."""
        esquema = self.argumentos.model_json_schema()
        esquema.pop("title", None)
        esquema.pop("description", None)
        for propiedad in esquema.get("properties", {}).values():
            propiedad.pop("title", None)
        esquema.setdefault("properties", {})
        esquema["additionalProperties"] = False
        return {"name": self.nombre, "description": self.descripcion, "input_schema": esquema}


def _mis_pedidos(
    sesion: Session, args: pedidos.ArgumentosMisPedidos, quien: Identidad
) -> Resultado:
    if quien.usuario_id is None:  # no debería pasar: la herramienta es solo de clientes
        raise PermissionError("Para ver pedidos hay que iniciar sesión en VisagShop")
    return pedidos.mis_pedidos(sesion, args, quien.usuario_id)


HERRAMIENTAS: tuple[Herramienta, ...] = (
    Herramienta(
        "buscar_productos",
        "Busca productos del catálogo de VisagShop por palabras, categoría, talla disponible "
        "y precio máximo en pesos colombianos. Úsala antes de recomendar o dar precios.",
        productos.FiltrosBusqueda,
        TODOS,
        lambda s, a, _q: productos.buscar_productos(s, a),
    ),
    Herramienta(
        "ver_producto",
        "Devuelve el detalle de un producto por su id (p042): descripción completa, precio, "
        "tallas y colores.",
        catalogo.ArgumentosProducto,
        TODOS,
        lambda s, a, _q: catalogo.ver_producto(s, a),
    ),
    Herramienta(
        "listar_categorias",
        "Lista las categorías de la tienda con cuántos productos tiene cada una y su rango "
        "de precios.",
        catalogo.SinArgumentos,
        TODOS,
        lambda s, a, _q: catalogo.listar_categorias(s, a),
    ),
    Herramienta(
        "mis_pedidos",
        "Pedidos del cliente que está conversando (solo los suyos): estado, fecha, productos "
        "y total. Opcionalmente uno por su número.",
        pedidos.ArgumentosMisPedidos,
        SOLO_CLIENTE,
        _mis_pedidos,
    ),
    Herramienta(
        "pedidos_pendientes",
        "Administrador: pedidos en estado nuevo o confirmado, del más antiguo al más reciente.",
        pedidos.ArgumentosPendientes,
        SOLO_ADMIN,
        lambda s, a, _q: pedidos.pedidos_pendientes(s, a),
    ),
    Herramienta(
        "resumen_ventas",
        "Administrador: pedidos por estado, total vendido, ticket promedio y productos más "
        "vendidos en los últimos N días.",
        pedidos.ArgumentosResumen,
        SOLO_ADMIN,
        lambda s, a, _q: pedidos.resumen_ventas(s, a),
    ),
    Herramienta(
        "productos_incompletos",
        "Administrador: productos a los que les faltan tallas o precio.",
        pedidos.ArgumentosIncompletos,
        SOLO_ADMIN,
        lambda s, a, _q: pedidos.productos_incompletos(s, a),
    ),
)

POR_NOMBRE = {h.nombre: h for h in HERRAMIENTAS}


def herramientas_para(rol: Rol) -> list[Herramienta]:
    return [h for h in HERRAMIENTAS if rol in h.roles]


@dataclass(frozen=True)
class ResultadoHerramienta:
    contenido: str
    es_error: bool = False


def ejecutar(sesion: Session, nombre: str, entrada: Any, quien: Identidad) -> ResultadoHerramienta:
    herramienta = POR_NOMBRE.get(nombre)
    if herramienta is None:
        return ResultadoHerramienta(f"La herramienta '{nombre}' no existe.", es_error=True)
    if quien.rol not in herramienta.roles:
        registro_log.warning("Herramienta %s pedida sin permiso por rol %s", nombre, quien.rol)
        return ResultadoHerramienta(
            "No tienes permiso para usar esta herramienta con tu tipo de cuenta.", es_error=True
        )
    try:
        argumentos = herramienta.argumentos.model_validate(entrada or {})
    except ValidationError as error:
        detalle = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
        return ResultadoHerramienta(f"Argumentos no válidos: {detalle}", es_error=True)

    try:
        resultado = herramienta.ejecutar(sesion, argumentos, quien)
    except (LookupError, PermissionError) as error:
        return ResultadoHerramienta(str(error), es_error=True)
    except Exception:
        registro_log.exception("Falló la herramienta %s", nombre)
        sesion.rollback()
        return ResultadoHerramienta(
            "No se pudo consultar la tienda en este momento.", es_error=True
        )

    texto = _a_json(resultado)
    if len(texto) > MAXIMO_CARACTERES_RESULTADO:
        texto = texto[:MAXIMO_CARACTERES_RESULTADO] + " …(resultado recortado)"
    return ResultadoHerramienta(texto)


def _a_json(resultado: Resultado) -> str:
    if isinstance(resultado, BaseModel):
        datos: Any = resultado.model_dump()
    else:
        datos = [r.model_dump() if isinstance(r, BaseModel) else r for r in resultado]
    return json.dumps(datos, ensure_ascii=False, default=str)
