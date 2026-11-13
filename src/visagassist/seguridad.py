"""Defensas contra prompt injection (cuando alguien intenta engañar al modelo con texto).

La defensa principal no está aquí sino en el diseño: el modelo solo puede usar herramientas
fijas de solo lectura, la identidad de quien pregunta viene firmada por VisagShop y cada
herramienta revisa permisos. Aunque el modelo fuera engañado, no tiene cómo leer datos
ajenos ni modificar nada. Este módulo agrega dos capas más:

1. Entrada: se quitan caracteres invisibles (de ancho cero, de control o que invierten el
   texto), una forma común de esconder instrucciones, y se normaliza el texto (NFKC).
2. Salida: si la respuesta contiene fragmentos de las instrucciones internas o algo con
   forma de clave de API, se reemplaza antes de mostrarla o guardarla.
"""

import re
import unicodedata

from visagassist.agente import INSTRUCCIONES_BASE, INSTRUCCIONES_ROL

MENSAJE_FILTRADO = "No puedo compartir esa información. ¿Te ayudo con algo de la tienda?"
_CATEGORIAS_INVISIBLES = {"Cc", "Cf", "Co", "Cs", "Cn"}
_PATRON_CLAVE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")
_LARGO_MINIMO_FRAGMENTO = 30


def limpiar_mensaje(texto: str) -> str:
    """Normaliza el mensaje del usuario y quita caracteres invisibles."""
    normalizado = unicodedata.normalize("NFKC", texto)
    visibles = "".join(
        c if unicodedata.category(c) not in _CATEGORIAS_INVISIBLES else " " for c in normalizado
    )
    return " ".join(visibles.split())


def _normalizar(texto: str) -> str:
    return " ".join(texto.lower().split())


def _fragmentos_secretos() -> list[str]:
    instrucciones = "\n".join([INSTRUCCIONES_BASE, *INSTRUCCIONES_ROL.values()])
    partes = re.split(r"[.\n:]", instrucciones)
    return [_normalizar(p) for p in partes if len(_normalizar(p)) >= _LARGO_MINIMO_FRAGMENTO]


_FRAGMENTOS = _fragmentos_secretos()


def revela_instrucciones(texto: str) -> bool:
    normalizado = _normalizar(texto)
    return any(fragmento in normalizado for fragmento in _FRAGMENTOS)


def filtrar_respuesta(texto: str) -> tuple[str, bool]:
    """Devuelve el texto a mostrar y si se bloqueó."""
    if revela_instrucciones(texto) or _PATRON_CLAVE.search(texto):
        return MENSAJE_FILTRADO, True
    return texto, False
