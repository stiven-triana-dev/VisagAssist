from dataclasses import dataclass

from visagassist.claude import ClienteClaude, ClienteHTTPClaude
from visagassist.config import Configuracion
from visagassist.gemini import ClienteGemini


@dataclass(frozen=True)
class Proveedor:
    nombre: str
    cliente: ClienteClaude
    modelo: str


def elegir_proveedor(configuracion: Configuracion) -> Proveedor | None:
    claude = configuracion.anthropic_api_key
    gemini = configuracion.gemini_api_key
    eleccion = configuracion.proveedor_ia
    if eleccion == "auto":
        eleccion = "claude" if claude else "gemini"

    if eleccion == "claude" and claude:
        return Proveedor(
            "claude", ClienteHTTPClaude(claude.get_secret_value()), configuracion.modelo_claude
        )
    if eleccion == "gemini" and gemini:
        return Proveedor(
            "gemini",
            ClienteGemini(gemini.get_secret_value(), tiempo_espera=120.0),
            configuracion.modelo_gemini,
        )
    return None
