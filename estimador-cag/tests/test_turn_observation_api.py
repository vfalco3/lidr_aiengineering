"""Tests de integración: el endpoint de sesión deja la observación del turno en el estado.

El LLM nunca se llama. :meth:`LLMWrapper._dispatch` se sustituye por un doble que
devuelve una respuesta fija con uso de tokens conocido, así el coste es calculable.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_llm_wrapper, get_session_store
from app.routers import sessions
from app.services.llm_wrapper import LLMWrapper
from app.services.sessions import SessionStore
from tests.sample_data import SAMPLE_ANSWER, TRANSCRIPT_FIRST_TURN, TRANSCRIPT_FOLLOW_UP


def _completion(content: str) -> SimpleNamespace:
    """Respuesta con la forma de LiteLLM: 100 tokens de entrada y 50 de salida, modelo gpt-4o-mini.

    :param content: Texto de la estimación.
    :returns: Objeto con ``choices``, ``usage`` y ``model``.
    """
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        model="gpt-4o-mini",
    )


@pytest.fixture
def client():
    """Cliente de prueba con un wrapper cuya caché nunca acierta y un almacén nuevo.

    :returns: Un ``TestClient`` sobre un FastAPI mínimo con solo el router de sesiones.
    """
    cache = MagicMock()
    cache.get.return_value = None
    wrapper = LLMWrapper(
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
        primary_model="gpt-4o-mini",
        fallback_model="claude-haiku-4-5",
        timeout=5,
        num_retries=0,
        cache=cache,
    )
    wrapper._dispatch = lambda **kwargs: _completion(SAMPLE_ANSWER)  # type: ignore[method-assign]

    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[get_llm_wrapper] = lambda: wrapper
    app.dependency_overrides[get_session_store] = lambda: SessionStore(max_turns=6)
    return TestClient(app)


def test_state_exposes_last_turn_observation_after_two_turns(client):
    session_id = client.post("/sessions").json()["session_id"]
    assert client.get(f"/sessions/{session_id}").json()["last_turn_observation"] is None

    client.post(f"/sessions/{session_id}/estimate", data={"transcript": TRANSCRIPT_FIRST_TURN})
    client.post(f"/sessions/{session_id}/estimate", data={"transcript": TRANSCRIPT_FOLLOW_UP})

    observation = client.get(f"/sessions/{session_id}").json()["last_turn_observation"]
    assert observation["turn_index"] == 2
    assert observation["session_id"] == session_id
    assert observation["enriched_transcript_chars"] == len(TRANSCRIPT_FOLLOW_UP)
    assert observation["attachments_total_chars"] == 0
    assert observation["messages_in_window"] == 4
    assert observation["anchors_count"] == 0
    assert observation["summary_chars"] == 0
    assert observation["tokens_in"] == 100
    assert observation["tokens_out"] == 50
    assert observation["cache_hit_kind"] == "none"
    assert observation["last_resolved_tier"] is None
    assert observation["cost_usd"] == pytest.approx(round((100 * 0.15 + 50 * 0.6) / 1_000_000, 6))
    assert isinstance(observation["latency_ms"], int)
    assert observation["latency_ms"] >= 0


def test_attachment_characters_are_counted_in_observation(client):
    session_id = client.post("/sessions").json()["session_id"]
    pdf_text = b"Requisito: exportar a CSV el inventario.\n"

    response = client.post(
        f"/sessions/{session_id}/estimate",
        data={"transcript": TRANSCRIPT_FIRST_TURN},
        files=[("attachments", ("reqs.txt", pdf_text, "text/plain"))],
    )
    assert response.status_code == 200

    observation = client.get(f"/sessions/{session_id}").json()["last_turn_observation"]
    assert observation["attachments_total_chars"] == len(pdf_text.decode("utf-8"))
    assert observation["enriched_transcript_chars"] > len(TRANSCRIPT_FIRST_TURN)
