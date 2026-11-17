"""Tests de las métricas binarias del harness de estrés."""

from __future__ import annotations

import pytest

from evals.stress.metrics import (
    CostBudgetMetric,
    LatencyBudgetMetric,
    MemoryDriftMetric,
    MetricResult,
    run_all_metrics,
)


def test_latency_budget_passes_at_the_exact_limit():
    result = LatencyBudgetMetric(budget_ms=4000).evaluate({"latency_ms": 4000})

    assert isinstance(result, MetricResult)
    assert result.score == 1.0
    assert result.passed is True


def test_latency_budget_fails_one_millisecond_over():
    result = LatencyBudgetMetric(budget_ms=4000).evaluate({"latency_ms": 4001})

    assert result.score == 0.0
    assert result.passed is False
    assert "latency_ms=4001" in result.details


def test_latency_budget_rejects_non_positive_budget():
    with pytest.raises(ValueError):
        LatencyBudgetMetric(budget_ms=0)


def test_latency_budget_requires_the_field():
    with pytest.raises(KeyError, match="latency_ms"):
        LatencyBudgetMetric(budget_ms=4000).evaluate({"cost_usd": 0.1})


def test_cost_budget_passes_at_the_exact_limit_and_fails_above():
    metric = CostBudgetMetric(budget_usd=0.01)

    assert metric.evaluate({"cost_usd": 0.01}).passed is True
    assert metric.evaluate({"cost_usd": 0.0100001}).passed is False


def test_cost_budget_rejects_negative_budget():
    with pytest.raises(ValueError):
        CostBudgetMetric(budget_usd=-1)


def test_memory_drift_is_case_insensitive_substring_match():
    snapshot = {"summary": "", "anchors": [], "metadata": {"project_name": "GESTOR de inventario para almacén"}}

    result = MemoryDriftMetric("gestor de inventario", where=["metadata"]).evaluate(snapshot)

    assert result.score == 1.0


def test_memory_drift_fails_when_fact_is_absent():
    snapshot = {"summary": "resumen", "anchors": ["ancla"], "metadata": {"assumed_team_size": 3}}

    result = MemoryDriftMetric("80k€").evaluate(snapshot)

    assert result.score == 0.0
    assert "found_in=none" in result.details


def test_memory_drift_respects_the_where_restriction():
    snapshot = {"summary": "presupuesto de 80k€", "anchors": [], "metadata": {}}

    assert MemoryDriftMetric("80k€", where=["summary"]).evaluate(snapshot).passed is True
    assert MemoryDriftMetric("80k€", where=["metadata"]).evaluate(snapshot).passed is False


def test_memory_drift_searches_list_values_in_metadata():
    snapshot = {"metadata": {"mentioned_technologies": ["Python", "PostgreSQL"]}}

    assert MemoryDriftMetric("postgresql", where=["metadata"]).evaluate(snapshot).passed is True


def test_memory_drift_rejects_unknown_fields_and_empty_facts():
    with pytest.raises(ValueError, match="desconocidos"):
        MemoryDriftMetric("x", where=["resumen"])
    with pytest.raises(ValueError):
        MemoryDriftMetric("   ")
    with pytest.raises(ValueError):
        MemoryDriftMetric("x", where=[])


def test_run_all_metrics_keeps_order_and_applies_each_metric():
    observation = {"latency_ms": 5000, "cost_usd": 0.001}

    results = run_all_metrics(
        [LatencyBudgetMetric(4000), CostBudgetMetric(0.01)],
        observation,
    )

    assert [r.name for r in results] == ["latency_budget", "cost_budget"]
    assert [r.passed for r in results] == [False, True]
