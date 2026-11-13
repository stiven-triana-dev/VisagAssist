"""Calificador automático de las evaluaciones: reglas fijas, sin otro modelo de IA.

Cada caso dice qué herramientas debía usar el asistente (al menos una), cuáles tenía
prohibidas y qué debe (o no debe) aparecer en su respuesta. El texto se compara normalizado:
minúsculas, sin tildes y con los precios sin separadores ($130.000 -> 130000).

Métricas por caso:
- aprobado: cumple todas las reglas (la principal).
- herramienta: usó la herramienta esperada y ninguna prohibida.
- contenido: la respuesta trae lo esperado y nada de lo prohibido.
"""

import re
import unicodedata
from typing import Any


def normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c)
    )
    # 130.000 / 130,000 -> 130000 (separadores de miles entre dígitos)
    return re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", sin_tildes)


def fallas_de_herramientas(caso: dict[str, Any], usadas: list[str]) -> list[str]:
    fallas = []
    requeridas = caso.get("herramientas_alguna") or []
    if requeridas and not set(requeridas) & set(usadas):
        fallas.append(f"no usó ninguna de {requeridas}")
    prohibidas = set(caso.get("herramientas_prohibidas") or []) & set(usadas)
    if prohibidas:
        fallas.append(f"usó herramientas prohibidas {sorted(prohibidas)}")
    return fallas


def fallas_de_contenido(caso: dict[str, Any], respuesta: str) -> list[str]:
    texto = normalizar(respuesta)
    fallas = []
    for grupo in caso.get("contiene_todos") or []:
        if not any(normalizar(opcion) in texto for opcion in grupo):
            fallas.append(f"falta alguno de {grupo}")
    for prohibido in caso.get("no_contiene") or []:
        if normalizar(prohibido) in texto:
            fallas.append(f"contiene {prohibido!r}")
    for patron in caso.get("no_coincide") or []:
        if re.search(patron, texto):
            fallas.append(f"coincide con {patron!r}")
    for patron in caso.get("coincide") or []:
        # El formato se revisa sobre el texto original (con su $ y sus puntos).
        if not re.search(patron, respuesta):
            fallas.append(f"no coincide con {patron!r}")
    return fallas


def calificar(caso: dict[str, Any], respuesta: str, herramientas: list[str]) -> dict[str, Any]:
    de_herramientas = fallas_de_herramientas(caso, herramientas)
    de_contenido = fallas_de_contenido(caso, respuesta)
    todas = de_herramientas + de_contenido
    return {
        "grade": {
            "aprobado": 0.0 if todas else 1.0,
            "herramienta": 0.0 if de_herramientas else 1.0,
            "contenido": 0.0 if de_contenido else 1.0,
        },
        "explanation": {"aprobado": "; ".join(todas) or "cumple todo"},
    }
