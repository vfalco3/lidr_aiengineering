"""FastAPI dependency factories for shared singletons (cache and LLM wrapper)."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.cache import EstimationCache
from app.services.llm_wrapper import LLMWrapper
from app.services.sessions import SessionStore


@lru_cache
def get_cache() -> EstimationCache:
    settings = get_settings()
    return EstimationCache.from_url(settings.REDIS_URL, ttl=settings.CACHE_TTL)


@lru_cache
def get_llm_wrapper() -> LLMWrapper:
    settings = get_settings()
    return LLMWrapper(
        openai_api_key=settings.OPENAI_API_KEY,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        primary_model=settings.PRIMARY_MODEL,
        fallback_model=settings.FALLBACK_MODEL,
        timeout=settings.LLM_TIMEOUT,
        num_retries=settings.LLM_RETRIES,
        cache=get_cache(),
    )

@lru_cache
def get_session_store() -> SessionStore:
    """Devuelve el almacén de sesiones del proceso, dimensionado con ``MAX_TURNS``."""
    return SessionStore(max_turns=get_settings().MAX_TURNS)
