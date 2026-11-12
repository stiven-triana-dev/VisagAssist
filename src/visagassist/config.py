"""Configuración leída de variables de entorno (o de un archivo .env en desarrollo)."""

from functools import lru_cache

from pydantic import Field, PostgresDsn, SecretStr
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

    # Secreto compartido con VisagShop para firmar quién pregunta (cliente o administrador).
    secreto_identidad: SecretStr | None = Field(default=None, alias="VISAGASSIST_SECRETO")

    # Máximo de resultados que una herramienta devuelve al modelo.
    limite_resultados: int = Field(default=10, ge=1, le=50, alias="LIMITE_RESULTADOS")


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()  # type: ignore[call-arg]  # pydantic lee los valores del entorno
