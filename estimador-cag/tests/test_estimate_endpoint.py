"""Tests for ``POST /api/v1/estimate``.

The endpoint must:

* accept an ``EstimationRequest`` body,
* render the prompts through ``render_estimation_prompt``,
* send system and user prompts as two separate ``role`` messages,
* return an ``EstimationResponse`` with the model text and ``prompt_version="v1"``.

The LLM provider is never called: ``LLMWrapper._dispatch`` is replaced by a fake
that records the messages it receives.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import get_llm_wrapper
from app.prompts.loader import render_estimation_prompt
from app.routers import estimations
from app.schemas.estimation import EstimationRequest
from app.services.llm_wrapper import LLMWrapper

SAMPLE_PAYLOAD = {
    "description": (
        "Plataforma web para gestionar el inventario de un almacén con alertas de "
        "stock bajo, importación CSV y un panel de métricas para el responsable."
    ),
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}

FAKE_ESTIMATION_TEXT = "## Estimation\n\n| phase | duration_weeks | cost_eur | confidence_pct |\n"


def _fake_completion(content: str = FAKE_ESTIMATION_TEXT) -> SimpleNamespace:
    """Build an object shaped like a LiteLLM completion response.

    The assistant message carries ``content``, and the namespace exposes ``choices``,
    ``usage`` and ``model``.
    """
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=content),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=45, total_tokens=165),
        model="gpt-4o-mini",
    )


def _make_wrapper(dispatch) -> LLMWrapper:
    """Create a real ``LLMWrapper`` whose provider call is replaced by ``dispatch``.

    The cache is a mock that always misses, so every request reaches ``_dispatch``.

    ``dispatch`` replaces ``LLMWrapper._dispatch``. The returned wrapper is ready to be
    injected into the app.
    """
    fake_cache = MagicMock()
    fake_cache.get.return_value = None
    wrapper = LLMWrapper(
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
        primary_model="gpt-4o-mini",
        fallback_model="claude-haiku-4-5",
        timeout=5,
        num_retries=0,
        cache=fake_cache,
    )
    wrapper._dispatch = dispatch  # type: ignore[method-assign]
    return wrapper


@pytest.fixture
def recorded_calls() -> list[dict]:
    """Provide the list where the fake dispatch stores each call's kwargs.

    The list starts empty, and the fake dispatch appends to it.
    """
    return []


@pytest.fixture
def client(recorded_calls: list[dict]) -> TestClient:
    """Build a test client whose LLM wrapper records calls and returns a fixed completion.

    Every dispatched call's kwargs are appended to ``recorded_calls``. The returned
    ``TestClient`` is bound to a FastAPI app that includes only the estimations router.
    """

    def fake_dispatch(*, model_override, **kwargs):
        recorded_calls.append({"model_override": model_override, **kwargs})
        return _fake_completion()

    wrapper = _make_wrapper(fake_dispatch)
    app = FastAPI()
    app.include_router(estimations.router)
    app.dependency_overrides[get_llm_wrapper] = lambda: wrapper
    return TestClient(app)


def test_returns_text_and_prompt_version_v1(client: TestClient) -> None:
    """A valid request returns the model text tagged with ``prompt_version="v1"``."""
    response = client.post("/api/v1/estimate", json=SAMPLE_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body == {"text": FAKE_ESTIMATION_TEXT, "prompt_version": "v1"}


def test_sends_system_and_user_as_separate_messages(
    client: TestClient, recorded_calls: list[dict]
) -> None:
    """System and user prompts are dispatched as two messages with distinct roles."""
    client.post("/api/v1/estimate", json=SAMPLE_PAYLOAD)

    assert len(recorded_calls) == 1
    system_prompt, user_prompt = render_estimation_prompt(
        EstimationRequest(**SAMPLE_PAYLOAD), version="v1"
    )
    call = recorded_calls[0]
    assert call["messages"] == [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    assert system_prompt != user_prompt


def test_description_is_only_in_user_message(
    client: TestClient, recorded_calls: list[dict]
) -> None:
    """The project description travels in the user message, not in the system prompt."""
    client.post("/api/v1/estimate", json=SAMPLE_PAYLOAD)

    system_message, user_message = recorded_calls[0]["messages"]
    assert SAMPLE_PAYLOAD["description"] not in system_message["content"]
    assert SAMPLE_PAYLOAD["description"] in user_message["content"]
    assert "Project type: web_saas." in user_message["content"]


@pytest.mark.parametrize("output_format", ["phases_table", "line_items", "narrative"])
def test_output_format_is_rendered_into_system_prompt(
    client: TestClient, recorded_calls: list[dict], output_format: str
) -> None:
    """Each output format is rendered into the system prompt sent to the model."""
    payload = {**SAMPLE_PAYLOAD, "output_format": output_format}

    response = client.post("/api/v1/estimate", json=payload)

    assert response.status_code == 200
    system_message = recorded_calls[0]["messages"][0]
    assert f'output_format = "{output_format}"' in system_message["content"]


def test_missing_description_returns_422(client: TestClient) -> None:
    """A body without ``description`` is rejected by request validation."""
    payload = {k: v for k, v in SAMPLE_PAYLOAD.items() if k != "description"}

    response = client.post("/api/v1/estimate", json=payload)

    assert response.status_code == 422


def test_description_below_min_length_returns_422(client: TestClient) -> None:
    """A description shorter than 20 characters is rejected."""
    payload = {**SAMPLE_PAYLOAD, "description": "demasiado corta"}

    response = client.post("/api/v1/estimate", json=payload)

    assert response.status_code == 422


def test_unknown_output_format_returns_422(client: TestClient) -> None:
    """An ``output_format`` outside the enum is rejected."""
    payload = {**SAMPLE_PAYLOAD, "output_format": "markdown_soup"}

    response = client.post("/api/v1/estimate", json=payload)

    assert response.status_code == 422


def test_llm_failure_returns_500_with_detail() -> None:
    """A provider exception is turned into an HTTP 500 that carries the error message."""

    def failing_dispatch(**_kwargs):
        raise RuntimeError("provider down")

    wrapper = _make_wrapper(failing_dispatch)
    app = FastAPI()
    app.include_router(estimations.router)
    app.dependency_overrides[get_llm_wrapper] = lambda: wrapper
    client = TestClient(app)

    response = client.post("/api/v1/estimate", json=SAMPLE_PAYLOAD)

    assert response.status_code == 500
    assert "provider down" in response.json()["detail"]
