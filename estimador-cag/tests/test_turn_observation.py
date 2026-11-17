"""Tests unitarios de la observación unificada por turno.

Usan diccionarios de respuesta fijos. No llaman al LLM ni levantan FastAPI.
"""

from __future__ import annotations

import pytest

from app.services.observability import build_turn_observation

_RESULT = {
    "estimation": "## Proyecto",
    "model": "gpt-4o-mini",
    "provider": "openai",
    "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    "cost_usd": 0.000045,
    "latency_ms": 812,
    "cache_hit": False,
}


def _observe(**overrides):
    """Construye una observación con datos de prueba y permite sobrescribir campos.

    :param overrides: Campos a sustituir en la llamada.
    :returns: El diccionario de observación.
    """
    kwargs = {
        "session_id": "sesion-demo",
        "turn_index": 2,
        "enriched_transcript_chars": 120,
        "attachments_total_chars": 0,
        "messages_in_window": 4,
        "anchors_count": 0,
        "summary_chars": 0,
        "result": _RESULT,
        "latency_ms": 900,
    }
    kwargs.update(overrides)
    return build_turn_observation(**kwargs)


def test_observation_contains_every_required_field():
    observation = _observe()

    expected_keys = {
        "turn_index",
        "session_id",
        "enriched_transcript_chars",
        "attachments_total_chars",
        "messages_in_window",
        "anchors_count",
        "summary_chars",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "latency_ms",
        "cache_hit_kind",
        "last_resolved_tier",
    }
    assert set(observation) == expected_keys


def test_cache_miss_reports_tokens_cost_and_none_kind():
    observation = _observe()

    assert observation["tokens_in"] == 100
    assert observation["tokens_out"] == 50
    assert observation["cost_usd"] == pytest.approx(0.000045)
    assert observation["cache_hit_kind"] == "none"
    assert observation["latency_ms"] == 900


def test_cache_hit_zeroes_tokens_and_cost_and_marks_exact():
    cached = {**_RESULT, "cache_hit": True}

    observation = _observe(result=cached, latency_ms=3)

    assert observation["tokens_in"] == 0
    assert observation["tokens_out"] == 0
    assert observation["cost_usd"] == 0.0
    assert observation["cache_hit_kind"] == "exact"
    assert observation["latency_ms"] == 3


def test_attachment_and_structure_fields_are_passed_through():
    observation = _observe(
        enriched_transcript_chars=5000,
        attachments_total_chars=4800,
        messages_in_window=6,
        last_resolved_tier="tier-2",
    )

    assert observation["enriched_transcript_chars"] == 5000
    assert observation["attachments_total_chars"] == 4800
    assert observation["messages_in_window"] == 6
    assert observation["last_resolved_tier"] == "tier-2"
    assert observation["anchors_count"] == 0
    assert observation["summary_chars"] == 0


def test_last_resolved_tier_defaults_to_none():
    assert _observe()["last_resolved_tier"] is None


def test_turn_index_must_be_one_based():
    with pytest.raises(ValueError, match="1-based"):
        _observe(turn_index=0)


def test_missing_usage_is_treated_as_zero_tokens():
    observation = _observe(result={"cost_usd": 0.0, "cache_hit": False})

    assert observation["tokens_in"] == 0
    assert observation["tokens_out"] == 0
