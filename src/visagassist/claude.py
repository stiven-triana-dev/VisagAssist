"""Cliente de la API de Claude (Messages API) por HTTP.

Se usa HTTP directo con httpx en vez del SDK oficial porque en el equipo de desarrollo
(Windows con Control de aplicaciones inteligente) una dependencia compilada del SDK queda
bloqueada. La API es un único endpoint: POST /v1/messages.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import httpx

URL_API = "https://api.anthropic.com/v1/messages"
VERSION_API = "2026-10-21"

# Errores que vale la pena reintentar: límite de peticiones, fallas del servidor y sobrecarga.
ESTADOS_REINTENTABLES = {408, 409, 429, 500, 502, 503, 504, 529}


@dataclass(frozen=True)
class Precio:
    """Precio en dólares por millón de tokens."""

    entrada: Decimal
    salida: Decimal
    lectura_cache: Decimal  # proporción del precio de entrada


# Precios por millón de tokens (USD). Haiku 5.5: tarifa para prompts de hasta 100K tokens.
PRECIOS: dict[str, Precio] = {
    "claude-haiku-5-5": Precio(Decimal("0.10"), Decimal("0.50"), Decimal("0.1")),
    "claude-sonnet-5-5": Precio(Decimal("2"), Decimal("10"), Decimal("0.05")),
    "claude-opus-5-5": Precio(Decimal("4"), Decimal("20"), Decimal("0.05")),
}
ESCRITURA_CACHE = Decimal("1.25")  # escribir en la caché de 5 minutos cuesta 1,25 veces la entrada


@dataclass(frozen=True)
class Uso:
    entrada: int = 0
    salida: int = 0
    cache_lectura: int = 0
    cache_escritura: int = 0

    def __add__(self, otro: "Uso") -> "Uso":
        return Uso(
            self.entrada + otro.entrada,
            self.salida + otro.salida,
            self.cache_lectura + otro.cache_lectura,
            self.cache_escritura + otro.cache_escritura,
        )

    @classmethod
    def desde_api(cls, datos: dict[str, Any]) -> "Uso":
        return cls(
            entrada=int(datos.get("input_tokens") or 0),
            salida=int(datos.get("output_tokens") or 0),
            cache_lectura=int(datos.get("cache_read_input_tokens") or 0),
            cache_escritura=int(datos.get("cache_creation_input_tokens") or 0),
        )


def costo_usd(modelo: str, uso: Uso) -> Decimal:
    precio = PRECIOS.get(modelo)
    if precio is None:
        raise ValueError(f"No hay precio registrado para el modelo {modelo}")
    millon = Decimal(1_000_000)
    total = (
        uso.entrada * precio.entrada
        + uso.cache_escritura * precio.entrada * ESCRITURA_CACHE
        + uso.cache_lectura * precio.entrada * precio.lectura_cache
        + uso.salida * precio.salida
    ) / millon
    return total.quantize(Decimal("0.000001"))


@dataclass(frozen=True)
class RespuestaClaude:
    contenido: list[dict[str, Any]]
    motivo_parada: str  # end_turn, tool_use, max_tokens, refusal, pause_turn...
    uso: Uso
    modelo: str


class ErrorClaude(Exception):
    """Error al llamar a la API de Claude."""

    def __init__(self, mensaje: str, estado: int | None = None) -> None:
        super().__init__(mensaje)
        self.estado = estado


class ClienteClaude(Protocol):
    """Lo que el agente necesita de Claude. En las pruebas se reemplaza por uno simulado."""

    def crear_mensaje(self, peticion: dict[str, Any]) -> RespuestaClaude: ...


class ClienteHTTPClaude:
    def __init__(
        self,
        clave_api: str,
        *,
        reintentos: int = 2,
        tiempo_espera: float = 60.0,
        transporte: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._http = httpx.Client(
            timeout=tiempo_espera,
            transport=transporte,
            headers={
                "x-api-key": clave_api,
                "anthropic-version": VERSION_API,
                "content-type": "application/json",
            },
        )
        self._reintentos = reintentos
        self._dormir = dormir

    def crear_mensaje(self, peticion: dict[str, Any]) -> RespuestaClaude:
        for intento in range(self._reintentos + 1):
            ultimo = intento == self._reintentos
            try:
                respuesta = self._http.post(URL_API, json=peticion)
            except httpx.TransportError as error:
                if ultimo:
                    raise ErrorClaude(f"Sin conexión con la API de Claude: {error}") from error
                self._dormir(2**intento)
                continue

            if respuesta.status_code == 200:
                datos = respuesta.json()
                return RespuestaClaude(
                    contenido=list(datos.get("content") or []),
                    motivo_parada=str(datos.get("stop_reason")),
                    uso=Uso.desde_api(datos.get("usage") or {}),
                    modelo=str(datos.get("model", peticion.get("model", ""))),
                )
            if respuesta.status_code in ESTADOS_REINTENTABLES and not ultimo:
                self._dormir(_espera(respuesta, intento))
                continue
            raise ErrorClaude(_mensaje_error(respuesta), respuesta.status_code)
        raise AssertionError("inalcanzable")  # pragma: no cover

    def cerrar(self) -> None:
        self._http.close()


def _espera(respuesta: httpx.Response, intento: int) -> float:
    """Respeta el encabezado retry-after si viene (con tope de 10 s); si no, 1 s, 2 s..."""
    valor = respuesta.headers.get("retry-after")
    try:
        return min(float(valor), 10.0) if valor else float(2**intento)
    except ValueError:
        return float(2**intento)


def _mensaje_error(respuesta: httpx.Response) -> str:
    try:
        error = respuesta.json().get("error", {})
        return f"{error.get('type', 'error')}: {error.get('message', '')}".strip()
    except ValueError:
        return f"HTTP {respuesta.status_code}"
