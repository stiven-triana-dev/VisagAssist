"""Configuración leída de variables de entorno (o de un archivo .env en desarrollo)."""

from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Configuracion(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Conexión a la base de VisagShop con un usuario de SOLO LECTURA.
    # Ejemplo: postgresql+pg8000://visagassist_lectura:CLAVE@HOST/BASE?sslmode=require
    database_url: PostgresDsn = Field(alias="DATABASE_URL")

    # Máximo de resultados que una herramienta devuelve al modelo.
    limite_resultados: int = Field(default=10, ge=1, le=50, alias="LIMITE_RESULTADOS")


@lru_cache
def obtener_configuracion() -> Configuracion:
    return Configuracion()  # type: ignore[call-arg]  # pydantic lee los valores del entorno
