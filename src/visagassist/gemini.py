"""Adaptador para usar Gemini (Google) como proveedor del agente.

El agente está escrito con el formato de la API de Claude (Messages API). Este adaptador
recibe esa misma petición, la traduce al formato de Gemini (generateContent), llama a la API
y traduce la respuesta de vuelta. Así el agente, las herramientas, la seguridad y las pruebas
no cambian: solo cambia quién responde. Se usa con el plan gratuito de Google AI Studio.

Equivalencias principales:
  system                      -> systemInstruction
  tools[] (input_schema)      -> tools[0].functionDeclarations[] (parametersJsonSchema)
  rol "assistant"             -> rol "model"
  bloque tool_use             -> parte functionCall
  bloque tool_result          -> parte functionResponse (con el nombre de la herramienta)
  stop_reason                 <- finishReason (STOP, MAX_TOKENS, SAFETY...)
Gemini firma su razonamiento (thoughtSignature) y pide recibir la firma de vuelta: cada
bloque traducido guarda la parte original de Gemini en "_parte_gemini" y se devuelve igual.
"""

import time
from collections.abc import Callable
from typing import Any

import httpx

from visagassist.claude import (
    ESTADOS_REINTENTABLES,
    ErrorClaude,
    RespuestaClaude,
    Uso,
    _espera,
)

URL_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
PARTE_ORIGINAL = "_parte_gemini"
RECHAZOS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}


# ----------------------------------------------------------------- petición


def traducir_peticion(peticion: dict[str, Any]) -> dict[str, Any]:
    cuerpo: dict[str, Any] = {
        "contents": _contenidos(peticion.get("messages") or []),
        "generationConfig": {"maxOutputTokens": int(peticion.get("max_tokens", 8192))},
    }
    sistema = "\n\n".join(b.get("text", "") for b in peticion.get("system") or [])
    if sistema:
        cuerpo["systemInstruction"] = {"parts": [{"text": sistema}]}
    herramientas = peticion.get("tools") or []
    if herramientas:
        cuerpo["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": h["name"],
                        "description": h["description"],
                        "parametersJsonSchema": h["input_schema"],
                    }
                    for h in herramientas
                ]
            }
        ]
    return cuerpo


def _contenidos(mensajes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nombres_por_id: dict[str, str] = {}
    contenidos: list[dict[str, Any]] = []
    for mensaje in mensajes:
        rol = "model" if mensaje["role"] == "assistant" else "user"
        contenido = mensaje["content"]
        if isinstance(contenido, str):
            contenidos.append({"role": rol, "parts": [{"text": contenido}]})
            continue
        partes: list[dict[str, Any]] = []
        for bloque in contenido:
            if PARTE_ORIGINAL in bloque:  # vino de Gemini: se devuelve tal cual (con su firma)
                partes.append(bloque[PARTE_ORIGINAL])
                if bloque.get("type") == "tool_use":
                    nombres_por_id[bloque["id"]] = bloque["name"]
                continue
            tipo = bloque.get("type")
            if tipo == "text":
                partes.append({"text": bloque.get("text", "")})
            elif tipo == "tool_use":
                nombres_por_id[bloque["id"]] = bloque["name"]
                partes.append(
                    {
                        "functionCall": {
                            "id": bloque["id"],
                            "name": bloque["name"],
                            "args": bloque.get("input") or {},
                        }
                    }
                )
            elif tipo == "tool_result":
                clave = "error" if bloque.get("is_error") else "resultado"
                partes.append(
                    {
                        "functionResponse": {
                            "id": bloque["tool_use_id"],
                            "name": nombres_por_id.get(bloque["tool_use_id"], "herramienta"),
                            "response": {clave: bloque.get("content", "")},
                        }
                    }
                )
            # Los bloques de razonamiento sin parte original no se envían.
        if partes:
            contenidos.append({"role": rol, "parts": partes})
    return contenidos


# ----------------------------------------------------------------- respuesta


def traducir_respuesta(datos: dict[str, Any], modelo_pedido: str) -> RespuestaClaude:
    uso = _uso(datos.get("usageMetadata") or {})
    modelo = str(datos.get("modelVersion") or modelo_pedido)
    candidatos = datos.get("candidates") or []
    if not candidatos:
        # Gemini bloqueó la pregunta antes de responder (promptFeedback.blockReason).
        return RespuestaClaude([], "refusal", uso, modelo)

    candidato = candidatos[0]
    bloques: list[dict[str, Any]] = []
    for numero, parte in enumerate((candidato.get("content") or {}).get("parts") or []):
        if "functionCall" in parte:
            llamada = parte["functionCall"]
            bloques.append(
                {
                    "type": "tool_use",
                    "id": llamada.get("id") or f"gemini_{numero}",
                    "name": llamada.get("name", ""),
                    "input": llamada.get("args") or {},
                    PARTE_ORIGINAL: parte,
                }
            )
        elif parte.get("thought"):
            bloques.append({"type": "thinking", "thinking": "", PARTE_ORIGINAL: parte})
        elif "text" in parte:
            bloques.append({"type": "text", "text": parte["text"], PARTE_ORIGINAL: parte})

    motivo = str(candidato.get("finishReason") or "STOP")
    if any(b["type"] == "tool_use" for b in bloques):
        parada = "tool_use"
    elif motivo == "MAX_TOKENS":
        parada = "max_tokens"
    elif motivo in RECHAZOS:
        parada = "refusal"
    else:
        parada = "end_turn"
    return RespuestaClaude(bloques, parada, uso, modelo)


def _uso(datos: dict[str, Any]) -> Uso:
    en_cache = int(datos.get("cachedContentTokenCount") or 0)
    return Uso(
        entrada=int(datos.get("promptTokenCount") or 0) - en_cache,
        salida=int(datos.get("candidatesTokenCount") or 0)
        + int(datos.get("thoughtsTokenCount") or 0),
        cache_lectura=en_cache,
    )


# ----------------------------------------------------------------- cliente


class ClienteGemini:
    """Mismo contrato que ClienteHTTPClaude: recibe y devuelve el formato de Claude."""

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
            headers={"x-goog-api-key": clave_api, "content-type": "application/json"},
        )
        self._reintentos = reintentos
        self._dormir = dormir

    def crear_mensaje(self, peticion: dict[str, Any]) -> RespuestaClaude:
        modelo = str(peticion["model"])
        url = f"{URL_BASE}/{modelo}:generateContent"
        cuerpo = traducir_peticion(peticion)
        for intento in range(self._reintentos + 1):
            ultimo = intento == self._reintentos
            try:
                respuesta = self._http.post(url, json=cuerpo)
            except httpx.TransportError as error:
                if ultimo:
                    raise ErrorClaude(f"Sin conexión con la API de Gemini: {error}") from error
                self._dormir(2**intento)
                continue
            if respuesta.status_code == 200:
                return traducir_respuesta(respuesta.json(), modelo)
            if respuesta.status_code in ESTADOS_REINTENTABLES and not ultimo:
                self._dormir(_espera(respuesta, intento))
                continue
            raise ErrorClaude(_mensaje_error(respuesta), respuesta.status_code)
        raise AssertionError("inalcanzable")  # pragma: no cover


def _mensaje_error(respuesta: httpx.Response) -> str:
    try:
        error = respuesta.json().get("error", {})
        return f"{error.get('status', 'error')}: {error.get('message', '')}".strip()
    except ValueError:
        return f"HTTP {respuesta.status_code}"
