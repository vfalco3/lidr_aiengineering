from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and the ``.env`` file."""

    # Configuración de la Aplicación
    APP_NAME: str = Field(default="Estimador CAG")
    APP_ENV: str = Field(default="development")
    DEBUG: bool = Field(default=True)

    ANTHROPIC_API_KEY: str | None = Field(default=None)
    ANTHROPIC_MODEL: str = Field(default="claude-3-5-sonnet-latest")

    # Proveedor por defecto activo ('openai' o 'anthropic')
    LLM_PROVIDER: str = Field(default="anthropic")

    # Wrapper del LLM: modelos, claves, tiempos de espera y reintentos.
    PRIMARY_MODEL: str = Field(default="claude-haiku-4-5")
    FALLBACK_MODEL: str = Field(default="gpt-4o-mini")
    OPENAI_API_KEY: str | None = Field(default=None)
    LLM_TIMEOUT: int = Field(default=60, ge=1)
    LLM_RETRIES: int = Field(default=2, ge=0)

    # Caché exacta: Redis debe estar levantado (p. ej. docker run -p 6379:6379 redis:7).
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    CACHE_TTL: int = Field(default=86400, ge=1)

    # Ventana deslizante de sesiones: número de pares usuario+asistente que se envían al LLM
    MAX_TURNS: int = Field(default=6, ge=1)

    # Configuración del archivo .env con Pydantic V2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignora variables extra del .env que no estén declaradas arriba
    )

    @property
    def LLM_MODEL(self) -> str:
        """Return the model name for the active provider.

        It returns ``OPENAI_MODEL`` when the provider is ``openai``, otherwise ``ANTHROPIC_MODEL``.
        """
        return  self.ANTHROPIC_MODEL


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings.

    The settings are read once per process. Call ``get_settings.cache_clear()`` to reload them.

    """
    return Settings()


# Instancia global para importar en el resto de la aplicación
settings = get_settings()
