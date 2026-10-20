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

    # Configuración del archivo .env con Pydantic V2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Ignora variables extra del .env que no estén declaradas arriba
    )

    @property
    def LLM_MODEL(self) -> str:
        """Return the model name for the active provider.

        :return: ``OPENAI_MODEL`` when the provider is ``openai``, otherwise ``ANTHROPIC_MODEL``.
        :rtype: str
        """
        return  self.ANTHROPIC_MODEL


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings.

    The settings are read once per process. Call ``get_settings.cache_clear()`` to reload them.

    :return: The settings instance.
    :rtype: Settings
    """
    return Settings()


# Instancia global para importar en el resto de la aplicación
settings = get_settings()
