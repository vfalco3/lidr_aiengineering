"""Genera ``REPORT.md`` a partir del CSV producido por :mod:`evals.stress.run`.

Solo calcula tablas y estadísticos; no interpreta resultados. La sección de lectura
se redacta a mano después de ejecutar el harness en vivo, con los números a la vista.

Uso::

    uv run python -m evals.stress.report --csv evals/stress/results.csv --output evals/stress/REPORT.md
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from evals.stress.scenarios import PROFILE_NAMES

#: Puntos de la curva por número de turno.
CURVE_POINTS: tuple[int, ...] = (1, 3, 6, 10, 20)

_NUMERIC_FIELDS = (
    "repeat",
    "attachment_kb",
    "turn_index",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "cumulative_cost_usd",
    "latency_ms",
    "memory_drift_score",
    "stale_present",
    "marker_recall",
    "latency_budget_ok",
    "cost_budget_ok",
)


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Percentil por rango más cercano (nearest-rank).

    :param values: Valores de la muestra; pueden venir en cualquier orden.
    :param pct: Percentil entre 0 y 100.
    :returns: El valor del percentil, o ``None`` si la muestra está vacía.
    :raises ValueError: Si ``pct`` está fuera de [0, 100].
    """
    if not 0 <= pct <= 100:
        raise ValueError("pct debe estar entre 0 y 100")
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _mean(values: Iterable[float]) -> float | None:
    """Media aritmética de una colección, o ``None`` si está vacía.

    :param values: Valores numéricos.
    :returns: La media, o ``None``.
    """
    items = list(values)
    return sum(items) / len(items) if items else None


def _fmt(value: float | None, digits: int = 2) -> str:
    """Formatea un número para una celda de Markdown.

    :param value: Número a formatear, o ``None``.
    :param digits: Decimales.
    :returns: El número con ``digits`` decimales, o ``—`` si falta.
    """
    return "—" if value is None else f"{value:.{digits}f}"


def load_rows(path: Path) -> list[dict[str, Any]]:
    """Lee el CSV del runner y convierte los campos numéricos.

    Las celdas vacías pasan a ``None``. Los campos que no son numéricos quedan como texto.

    :param path: Ruta del CSV.
    :returns: Una lista de diccionarios, uno por fila.
    """
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for field in _NUMERIC_FIELDS:
            raw = row.get(field, "")
            row[field] = float(raw) if raw not in ("", None) else None
    return rows


def _profile_rows(rows: Sequence[dict[str, Any]], scenario: str) -> list[dict[str, Any]]:
    """Filtra las filas de un escenario.

    :param rows: Todas las filas del CSV.
    :param scenario: Nombre del escenario.
    :returns: Las filas de ese escenario.
    """
    return [row for row in rows if row["scenario"] == scenario]


def _summary_table(rows: Sequence[dict[str, Any]]) -> str:
    """Tabla resumen por escenario: latencia P50/P95, coste, hit rate de caché y recall medio.

    :param rows: Filas del CSV.
    :returns: La tabla en Markdown.
    """
    lines = [
        "| Escenario | Filas | P50 latencia (ms) | P95 latencia (ms) | Coste acumulado medio por ejecución (USD) | Hit rate caché exacta | Recall medio fact-tracker |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for scenario in (*PROFILE_NAMES, "attachment"):
        subset = _profile_rows(rows, scenario)
        if not subset:
            continue
        latencies = [row["latency_ms"] for row in subset if row["latency_ms"] is not None]
        per_run_totals = _run_totals(subset)
        hits = sum(row["cache_hit_kind"] == "exact" for row in subset)
        drift = [row["memory_drift_score"] for row in subset if row["memory_drift_score"] is not None]
        recall = [row["marker_recall"] for row in subset if row["marker_recall"] is not None]
        recall_value = _mean(drift) if drift else _mean(recall)
        lines.append(
            f"| {scenario} | {len(subset)} | {_fmt(percentile(latencies, 50), 0)} | "
            f"{_fmt(percentile(latencies, 95), 0)} | {_fmt(_mean(per_run_totals), 6)} | "
            f"{_fmt(hits / len(subset) if subset else None, 2)} | {_fmt(recall_value, 2)} |"
        )
    return "\n".join(lines)


def _run_totals(rows: Sequence[dict[str, Any]]) -> list[float]:
    """Coste acumulado final de cada ejecución (escenario, repetición).

    :param rows: Filas de un mismo escenario.
    :returns: Un total por ejecución, el del último turno.
    """
    last: dict[tuple[Any, Any], float] = {}
    for row in rows:
        key = (row["repeat"], row["attachment_kb"])
        if row["cumulative_cost_usd"] is not None:
            last[key] = max(last.get(key, 0.0), row["cumulative_cost_usd"])
    return list(last.values())


def _curve_latency_vs_tokens(rows: Sequence[dict[str, Any]]) -> str:
    """Curva latencia frente a tokens de entrada, en los puntos :data:`CURVE_POINTS`.

    :param rows: Filas de los perfiles.
    :returns: La tabla en Markdown.
    """
    profile = [row for row in rows if row["scenario"] in PROFILE_NAMES]
    lines = [
        "| N (turno) | Tokens entrada P50 | Latencia P50 (ms) | Latencia P95 (ms) |",
        "|---:|---:|---:|---:|",
    ]
    for point in CURVE_POINTS:
        at_point = [row for row in profile if int(row["turn_index"]) == point]
        tokens = [row["tokens_in"] for row in at_point if row["tokens_in"] is not None]
        latencies = [row["latency_ms"] for row in at_point if row["latency_ms"] is not None]
        lines.append(
            f"| {point} | {_fmt(percentile(tokens, 50), 0)} | "
            f"{_fmt(percentile(latencies, 50), 0)} | {_fmt(percentile(latencies, 95), 0)} |"
        )
    return "\n".join(lines)


def _curve_cost_vs_turn(rows: Sequence[dict[str, Any]]) -> str:
    """Curva de coste acumulado frente al turno, media sobre perfiles y repeticiones.

    :param rows: Filas de los perfiles.
    :returns: La tabla en Markdown.
    """
    profile = [row for row in rows if row["scenario"] in PROFILE_NAMES]
    lines = ["| N (turno) | Coste acumulado medio (USD) |", "|---:|---:|"]
    for point in CURVE_POINTS:
        at_point = [row["cumulative_cost_usd"] for row in profile if int(row["turn_index"]) == point]
        lines.append(f"| {point} | {_fmt(_mean(at_point), 6)} |")
    return "\n".join(lines)


def _curve_recall_vs_turn(rows: Sequence[dict[str, Any]]) -> str:
    """Curva de recall del fact-tracker frente a N, una columna por perfil.

    :param rows: Filas de los perfiles.
    :returns: La tabla en Markdown; ``—`` cuando no hay hechos evaluables en ese turno.
    """
    header = "| N (turno) | " + " | ".join(PROFILE_NAMES) + " |"
    divider = "|---:|" + "---:|" * len(PROFILE_NAMES)
    lines = [header, divider]
    for point in CURVE_POINTS:
        cells = []
        for scenario in PROFILE_NAMES:
            values = [
                row["memory_drift_score"]
                for row in _profile_rows(rows, scenario)
                if int(row["turn_index"]) == point and row["memory_drift_score"] is not None
            ]
            cells.append(_fmt(_mean(values), 2))
        lines.append(f"| {point} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _attachment_table(rows: Sequence[dict[str, Any]]) -> str:
    """Tabla por tamaño de adjunto: latencia, coste y recall de marcadores.

    :param rows: Filas del escenario de adjuntos.
    :returns: La tabla en Markdown.
    """
    by_size: dict[float, list[dict[str, Any]]] = defaultdict(list)
    for row in _profile_rows(rows, "attachment"):
        by_size[row["attachment_kb"]].append(row)
    lines = [
        "| Adjunto (KiB) | Latencia P50 (ms) | Coste medio (USD) | Recall marcadores medio |",
        "|---:|---:|---:|---:|",
    ]
    for size in sorted(by_size):
        subset = by_size[size]
        latencies = [row["latency_ms"] for row in subset if row["latency_ms"] is not None]
        costs = [row["cost_usd"] for row in subset if row["cost_usd"] is not None]
        recall = [row["marker_recall"] for row in subset if row["marker_recall"] is not None]
        lines.append(
            f"| {int(size)} | {_fmt(percentile(latencies, 50), 0)} | "
            f"{_fmt(_mean(costs), 6)} | {_fmt(_mean(recall), 2)} |"
        )
    return "\n".join(lines)


def build_report(rows: Sequence[dict[str, Any]]) -> str:
    """Compone el Markdown del reporte con todas las tablas.

    :param rows: Filas del CSV, ya convertidas por :func:`load_rows`.
    :returns: El documento Markdown completo.
    """
    return "\n\n".join(
        [
            "# Reporte del harness de estrés",
            "## Resumen por escenario\n\n" + _summary_table(rows),
            "## Latencia frente a tokens de entrada\n\n" + _curve_latency_vs_tokens(rows),
            "## Coste acumulado frente al turno\n\n" + _curve_cost_vs_turn(rows),
            "## Recall de hechos frente a N\n\n" + _curve_recall_vs_turn(rows),
            "## Adjuntos por tamaño\n\n" + _attachment_table(rows),
            "## Lectura\n\n_Pendiente: redactar tras la ejecución en vivo, con los números de este reporte._",
        ]
    ) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada: lee el CSV y escribe el reporte.

    :param argv: Argumentos de línea de órdenes; ``None`` usa ``sys.argv``.
    :returns: 0 si todo fue bien.
    """
    parser = argparse.ArgumentParser(description="Genera REPORT.md a partir del CSV del harness de estrés.")
    parser.add_argument("--csv", default="evals/stress/results.csv")
    parser.add_argument("--output", default="evals/stress/REPORT.md")
    args = parser.parse_args(argv)
    report = build_report(load_rows(Path(args.csv)))
    Path(args.output).write_text(report, encoding="utf-8")
    print(f"reporte escrito en {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
