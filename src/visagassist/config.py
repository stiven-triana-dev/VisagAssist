"""Configuración leída de variables de entorno (o de un archivo .env en desarrollo)."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Conexión a la base de VisagShop con un usuario de SOLO LECTURA.
    # Ejemplo: postgresql+pg8000://visagassist_lectura:CLAVE@HOST/BASE?sslmode=require
    database_url: PostgresDsn = Field(alias="DATABASE_URL")

    # Base PROPIA del asistente (historial y costos). Es otra base: la de la tienda
    # nunca recibe escrituras. Ejemplo: postgresql+pg8000://visagassist:CLAVE@HOST/visagassist
    database_url_asistente: PostgresDsn | None = Field(default=None, alias="DATABASE_URL_ASISTENTE")

    # API de Claude. Sin clave, el chat responde 503 y el resto del servicio funciona.
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    modelo_claude: str = Field(default="claude-haiku-5-5", alias="MODELO_CLAUDE")

    # Gemini (Google AI Studio, plan gratuito) como proveedor alternativo.
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    modelo_gemini: str = Field(default="gemini-3.6-flash", alias="MODELO_GEMINI")

    # Qué proveedor responde: "claude", "gemini" o "auto" (Claude si hay clave; si no, Gemini).
    proveedor_ia: Literal["auto", "claude", "gemini"] = Field(default="auto", alias="PROVEEDOR_IA")

    # Secreto compartido con VisagShop para firmar quién pregunta (cliente o administrador).
    secreto_identidad: SecretStr | None = Field(default=None, alias="VISAGASSIST_SECRETO")

    # Máximo de resultados que una herramienta devuelve al modelo.
    limite_resultados: int = Field(default=10, ge=1, le=50, alias="LIMITE_RESULTADOS")

    # Límites de uso (ver limites.py): preguntas por hora y gasto máximo diario en dólares.
    limite_hora_invitado: int = Field(default=15, ge=1, alias="LIMITE_HORA_INVITADO")
    limite_hora_cliente: int = Field(default=30, ge=1, alias="LIMITE_HORA_CLIENTE")
    limite_hora_administrador: int = Field(default=60, ge=1, alias="LIMITE_HORA_ADMINISTRADOR")
    presupuesto_diario_usd: Decimal = Field(
        default=Decimal("1.00"), ge=0, alias="PRESUPUESTO_DIARIO_USD"
    )

    @field_validator(
        "anthropic_api_key",
        "gemini_api_key",
        "secreto_identidad",
        "database_url_asistente",
        mode="before",
    )
    @classmethod
    def _vacio_es_ninguno(cls, valor: object) -> object:
        """Una línea como "ANTHROPIC_API_KEY=" en el .env significa "sin clave"."""
        return None if isinstance(valor, str) and not valor.strip() else valor


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()  # type: ignore[call-arg]  # pydantic lee los valores del entorno
