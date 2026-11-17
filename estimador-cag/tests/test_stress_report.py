"""Tests del generador de REPORT.md con filas sintéticas fijas."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from evals.stress.report import CURVE_POINTS, build_report, load_rows, percentile
from evals.stress.run import COLUMNS


def _row(**overrides):
    """Fila de CSV con valores por defecto, convertida como lo haría :func:`load_rows`.

    :param overrides: Campos a sustituir.
    :returns: Diccionario de la fila.
    """
    base = {column: None for column in COLUMNS}
    base.update(
        scenario="growing",
        repeat=1.0,
        turn_index=1.0,
        tokens_in=1000.0,
        latency_ms=500.0,
        cost_usd=0.001,
        cumulative_cost_usd=0.001,
        cache_hit_kind="none",
        memory_drift_score=None,
        marker_recall=None,
        attachment_kb=None,
    )
    base.update(overrides)
    return base


def test_percentile_uses_nearest_rank():
    values = [10, 20, 30, 40]

    assert percentile(values, 50) == 20
    assert percentile(values, 95) == 40
    assert percentile(values, 0) == 10
    assert percentile([], 50) is None


def test_percentile_rejects_out_of_range():
    with pytest.raises(ValueError):
        percentile([1, 2], 101)


def test_report_has_every_section_and_no_invented_reading():
    rows = [
        _row(turn_index=t, cumulative_cost_usd=0.001 * t, tokens_in=1000.0 * t, latency_ms=400.0 + t)
        for t in CURVE_POINTS
    ]
    rows.append(_row(scenario="attachment", attachment_kb=5.0, turn_index=1.0, marker_recall=1.0))

    report = build_report(rows)

    for heading in (
        "## Resumen por escenario",
        "## Latencia frente a tokens de entrada",
        "## Coste acumulado frente al turno",
        "## Recall de hechos frente a N",
        "## Adjuntos por tamaño",
        "## Lectura",
    ):
        assert heading in report
    assert "Pendiente" in report


def test_summary_table_reports_cache_hit_rate_and_recall():
    rows = [
        _row(turn_index=1.0, cache_hit_kind="exact"),
        _row(turn_index=2.0, cache_hit_kind="none", memory_drift_score=1.0),
        _row(turn_index=3.0, cache_hit_kind="none", memory_drift_score=0.0),
    ]

    report = build_report(rows)

    line = next(line for line in report.splitlines() if line.startswith("| growing |"))
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    assert cells[5] == "0.33"
    assert cells[6] == "0.50"


def test_attachment_table_groups_by_size():
    rows = [
        _row(scenario="attachment", attachment_kb=0.0, latency_ms=300.0, cost_usd=0.001, marker_recall=None),
        _row(scenario="attachment", attachment_kb=100.0, latency_ms=900.0, cost_usd=0.004, marker_recall=0.5),
    ]

    report = build_report(rows)

    assert "| 0 | 300 |" in report
    assert "| 100 | 900 |" in report
    assert "| 100 | 900 | 0.004000 | 0.50 |" in report


def test_load_rows_converts_numbers_and_blanks(tmp_path: Path):
    path = tmp_path / "results.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow({**{c: "" for c in COLUMNS}, "scenario": "pivot", "turn_index": "5", "latency_ms": "812", "cost_usd": "0.0001"})

    rows = load_rows(path)

    assert rows[0]["turn_index"] == 5.0
    assert rows[0]["latency_ms"] == 812.0
    assert rows[0]["memory_drift_score"] is None
    assert rows[0]["scenario"] == "pivot"
