import copy
from typing import Any

from visagassist.claude import ErrorClaude, RespuestaClaude, Uso

USO_TIPICO = Uso(entrada=1000, salida=100)


def texto(contenido: str, uso: Uso = USO_TIPICO) -> RespuestaClaude:
    return RespuestaClaude(
        [{"type": "text", "text": contenido}], "end_turn", uso, "claude-haiku-5-5"
    )


def herramienta(
    nombre: str, entrada: dict[str, Any] | None = None, id_: str = "toolu_1", uso: Uso = USO_TIPICO
) -> RespuestaClaude:
    bloque = {"type": "tool_use", "id": id_, "name": nombre, "input": entrada or {}}
    return RespuestaClaude([bloque], "tool_use", uso, "claude-haiku-5-5")


def varias(*bloques: dict[str, Any], uso: Uso = USO_TIPICO) -> RespuestaClaude:
    return RespuestaClaude(list(bloques), "tool_use", uso, "claude-haiku-5-5")


def rechazo() -> RespuestaClaude:
    return RespuestaClaude([], "refusal", USO_TIPICO, "claude-haiku-5-5")


class ClaudeSimulado:
    def __init__(self, *guion: RespuestaClaude | ErrorClaude) -> None:
        self.guion = list(guion)
        self.peticiones: list[dict[str, Any]] = []

    def crear_mensaje(self, peticion: dict[str, Any]) -> RespuestaClaude:
        self.peticiones.append(copy.deepcopy(peticion))
        if not self.guion:
            raise AssertionError("El agente pidió más respuestas de las del guion")
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, ErrorClaude):
            raise siguiente
        return siguiente

    def ultimo_mensaje(self) -> dict[str, Any]:
        mensaje: dict[str, Any] = self.peticiones[-1]["messages"][-1]
        return mensaje
