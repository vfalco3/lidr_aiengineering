"""Runner del harness de estrés: orquesta escenarios y adjuntos y vuelca un CSV.

Uso, desde la raíz del repositorio::

    uv run python -m evals.stress.run --http http://localhost:8000 \\
        --scenarios growing,pivot,contradiction \\
        --attachment-sizes 0,5,20,50,100 \\
        --repeats 3 \\
        --output evals/stress/results.csv

Sin ``--http`` el runner usa un ``TestClient`` en proceso sobre ``app.main``. Ambos modos
hablan con el mismo cliente, :class:`RestStressClient`, que solo usa ``post`` y ``get``.

Cada ejecución crea una sesión nueva. La caché exacta del wrapper responde a entradas
idénticas, así que el primer turno de cada ejecución lleva un prefijo con el nombre del
escenario y el número de repetición. Así cada repetición mide llamadas reales al proveedor.

Una sola sesión de :data:`~evals.stress.scenarios.MAX_PROFILE_TURNS` turnos sirve para
todas las N: el historial es causal, así que el turno k es idéntico en una sesión corta
y en una larga. Esto evita pagar cinco veces el mismo prefijo.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx

from evals.stress.attachments import build_sized_pdf
from evals.stress.metrics import CostBudgetMetric, LatencyBudgetMetric, MemoryDriftMetric, run_all_metrics
from evals.stress.scenarios import (
    ATTACHMENT_FILENAME,
    ATTACHMENT_MARKERS,
    ATTACHMENT_TRANSCRIPT,
    PROFILE_NAMES,
    Scenario,
    build_profile,
)

#: Presupuesto de latencia por turno, en milisegundos.
DEFAULT_LATENCY_BUDGET_MS = 4000

#: Presupuesto de coste por turno, en dólares.
DEFAULT_COST_BUDGET_USD = 0.01

#: Columnas del CSV, en orden. Cada fila debe tener exactamente estas claves.
COLUMNS: tuple[str, ...] = (
    "scenario",
    "repeat",
    "attachment_kb",
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
    "cumulative_cost_usd",
    "latency_ms",
    "cache_hit_kind",
    "last_resolved_tier",
    "latency_budget_ok",
    "cost_budget_ok",
    "memory_drift_score",
    "stale_present",
    "marker_recall",
)

#: Campos de la observación ``turn_observed`` que se copian tal cual al CSV.
_OBSERVATION_COLUMNS: tuple[str, ...] = (
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
)


class RestStressClient:
    """Cliente del servicio de sesiones sobre cualquier objeto con ``post`` y ``get`` estilo httpx.

    Sirve tanto para ``httpx.Client`` contra un servidor real como para ``TestClient``
    en proceso.

    :param http: Cliente HTTP con la interfaz de ``httpx.Client``.
    """

    def __init__(self, http: Any) -> None:
        self._http = http

    def create_session(self) -> str:
        """Crea una sesión en el servicio.

        :returns: El ``session_id`` devuelto por ``POST /sessions``.
        :raises httpx.HTTPStatusError: Si el servicio responde con error.
        """
        response = self._http.post("/sessions")
        response.raise_for_status()
        return response.json()["session_id"]

    def estimate(self, session_id: str, transcript: str, attachments: Sequence[tuple[str, bytes]]) -> str:
        """Envía un turno con su transcripción y sus adjuntos como ``multipart/form-data``.

        :param session_id: Sesión en la que se añade el turno.
        :param transcript: Mensaje del usuario de este turno.
        :param attachments: Pares ``(nombre, bytes)`` de PDF adjuntos; puede estar vacío.
        :returns: El texto de la estimación devuelto por el servicio.
        :raises httpx.HTTPStatusError: Si el servicio responde con error.
        """
        files = [("attachments", (name, data, "application/pdf")) for name, data in attachments] or None
        response = self._http.post(
            f"/sessions/{session_id}/estimate",
            data={"transcript": transcript},
            files=files,
        )
        response.raise_for_status()
        return response.json()["text"]

    def state(self, session_id: str) -> dict[str, Any]:
        """Lee el estado de la sesión: metadatos y la última observación de turno.

        :param session_id: Sesión a consultar.
        :returns: El JSON de ``GET /sessions/{session_id}``.
        :raises httpx.HTTPStatusError: Si el servicio responde con error.
        """
        response = self._http.get(f"/sessions/{session_id}")
        response.raise_for_status()
        return response.json()


#: Identificador único de cada lanzamiento. Evita aciertos de caché contra respuestas de ejecuciones anteriores.
RUN_ID = uuid.uuid4().hex[:8]


def _with_nonce(transcript: str, label: str, repeat: int) -> str:
    """Antepone una etiqueta de ejecución a la transcripción para evitar aciertos de caché entre repeticiones.

    :param transcript: Mensaje original del turno.
    :param label: Nombre del escenario o del tamaño de adjunto.
    :param repeat: Número de repetición, desde 1.
    :returns: La transcripción con el prefijo ``[ejecución <label>-r<repeat>]``.
    """
    return f"[ejecución {label}-{RUN_ID}-r{repeat}] {transcript}"


def _observation(state: dict[str, Any]) -> dict[str, Any]:
    """Extrae la observación del último turno del estado de sesión.

    :param state: JSON de ``GET /sessions/{id}``.
    :returns: El diccionario ``last_turn_observation``.
    :raises RuntimeError: Si la sesión todavía no tiene ninguna observación.
    """
    observation = state.get("last_turn_observation")
    if observation is None:
        raise RuntimeError("la sesión no tiene observación de turno; ¿el servicio incluye turn_observed?")
    return observation


def _snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Construye el snapshot que evalúa :class:`MemoryDriftMetric`.

    ``summary`` y ``anchors`` van vacíos porque esta base de código no los mantiene.
    Así, los hechos solo pueden encontrarse en ``metadata``, y la métrica lo refleja.

    :param state: JSON de ``GET /sessions/{id}``.
    :returns: Diccionario con las claves ``summary``, ``anchors`` y ``metadata``.
    """
    return {"summary": "", "anchors": [], "metadata": state.get("project_metadata") or {}}


def _budget_flags(observation: dict[str, Any], latency_budget_ms: int, cost_budget_usd: float) -> tuple[int, int]:
    """Evalúa los dos presupuestos de un turno y devuelve 1 o 0 para cada uno.

    :param observation: Observación del turno.
    :param latency_budget_ms: Presupuesto de latencia en milisegundos.
    :param cost_budget_usd: Presupuesto de coste en dólares.
    :returns: Tupla ``(latency_budget_ok, cost_budget_ok)`` con valores 1 o 0.
    """
    results = run_all_metrics(
        [LatencyBudgetMetric(latency_budget_ms), CostBudgetMetric(cost_budget_usd)],
        observation,
    )
    return int(results[0].passed), int(results[1].passed)


def run_profile(
    client: RestStressClient,
    scenario: Scenario,
    *,
    repeat: int,
    latency_budget_ms: int,
    cost_budget_usd: float,
    on_row: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Ejecuta un perfil completo de :data:`MAX_PROFILE_TURNS` turnos en una sesión nueva.

    :param client: Cliente del servicio.
    :param scenario: Perfil a ejecutar.
    :param repeat: Número de repetición, para el nonce y la columna ``repeat``.
    :param latency_budget_ms: Presupuesto de latencia por turno.
    :param cost_budget_usd: Presupuesto de coste por turno.
    :returns: Una fila por turno, con las columnas de :data:`COLUMNS`.
    """
    session_id = client.create_session()
    rows: list[dict[str, Any]] = []
    cumulative = 0.0
    for turn_index, transcript in enumerate(scenario.transcripts, start=1):
        if turn_index == 1:
            transcript = _with_nonce(transcript, scenario.name, repeat)
        client.estimate(session_id, transcript, [])
        state = client.state(session_id)
        observation = _observation(state)
        snapshot = _snapshot(state)

        cumulative += float(observation["cost_usd"])
        latency_ok, cost_ok = _budget_flags(observation, latency_budget_ms, cost_budget_usd)

        due = scenario.facts_due_at(turn_index)
        drift_scores = [
            MemoryDriftMetric(fact.text, fact.where).evaluate(snapshot).score for fact in due
        ]
        superseded = scenario.superseded_due_at(turn_index)
        stale_present = (
            any(MemoryDriftMetric(fact.text).evaluate(snapshot).passed for fact in superseded)
            if superseded
            else None
        )

        row: dict[str, Any] = {
            "scenario": scenario.name,
            "repeat": repeat,
            "attachment_kb": None,
            "turn_index": turn_index,
            **{key: observation.get(key) for key in _OBSERVATION_COLUMNS},
            "cumulative_cost_usd": round(cumulative, 6),
            "latency_budget_ok": latency_ok,
            "cost_budget_ok": cost_ok,
            "memory_drift_score": (sum(drift_scores) / len(drift_scores)) if drift_scores else None,
            "stale_present": None if stale_present is None else int(stale_present),
            "marker_recall": None,
        }
        rows.append(row)
        if on_row is not None:
            on_row(row)
        print(f"  turno {turn_index}/{len(scenario.transcripts)} · {row['latency_ms']} ms · {row['cost_usd']} USD", flush=True)
    return rows


def run_attachment(
    client: RestStressClient,
    *,
    size_kb: int,
    repeat: int,
    latency_budget_ms: int,
    cost_budget_usd: float,
) -> dict[str, Any]:
    """Ejecuta una estimación inicial con un PDF de tamaño calibrado y mide el recall de sus marcadores.

    :param client: Cliente del servicio.
    :param size_kb: Tamaño del PDF en KiB; 0 significa sin adjunto (línea base).
    :param repeat: Número de repetición.
    :param latency_budget_ms: Presupuesto de latencia.
    :param cost_budget_usd: Presupuesto de coste.
    :returns: Una única fila con las columnas de :data:`COLUMNS`.
    """
    session_id = client.create_session()
    transcript = _with_nonce(ATTACHMENT_TRANSCRIPT, f"adjunto-{size_kb}kb", repeat)
    attachments = [] if size_kb == 0 else [(ATTACHMENT_FILENAME, build_sized_pdf(size_kb))]
    text = client.estimate(session_id, transcript, attachments)
    observation = _observation(client.state(session_id))
    latency_ok, cost_ok = _budget_flags(observation, latency_budget_ms, cost_budget_usd)

    recall = None
    if attachments:
        found = sum(marker.casefold() in text.casefold() for marker in ATTACHMENT_MARKERS)
        recall = found / len(ATTACHMENT_MARKERS)

    return {
        "scenario": "attachment",
        "repeat": repeat,
        "attachment_kb": size_kb,
        "turn_index": 1,
        **{key: observation.get(key) for key in _OBSERVATION_COLUMNS},
        "cumulative_cost_usd": round(float(observation["cost_usd"]), 6),
        "latency_budget_ok": latency_ok,
        "cost_budget_ok": cost_ok,
        "memory_drift_score": None,
        "stale_present": None,
        "marker_recall": recall,
    }


def run_stress(
    client: RestStressClient,
    *,
    scenarios: Sequence[str],
    sizes_kb: Sequence[int],
    repeats: int,
    latency_budget_ms: int = DEFAULT_LATENCY_BUDGET_MS,
    cost_budget_usd: float = DEFAULT_COST_BUDGET_USD,
    on_row: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Ejecuta todos los perfiles y tamaños de adjunto, tantas veces como indique ``repeats``.

    El orden es repetición primero, después perfiles y después adjuntos, para que un
    corte a mitad deje repeticiones completas en el CSV.

    :param client: Cliente del servicio.
    :param scenarios: Nombres de perfil, de :data:`~evals.stress.scenarios.PROFILE_NAMES`.
    :param sizes_kb: Tamaños de adjunto en KiB; 0 es la línea base sin adjunto.
    :param repeats: Número de repeticiones completas, desde 1.
    :param latency_budget_ms: Presupuesto de latencia por turno.
    :param cost_budget_usd: Presupuesto de coste por turno.
    :returns: Todas las filas, en el orden de ejecución.
    :raises ValueError: Si ``repeats`` es menor que 1 o un perfil no existe.
    """
    if repeats < 1:
        raise ValueError("repeats debe ser al menos 1")
    unknown = [name for name in scenarios if name not in PROFILE_NAMES]
    if unknown:
        raise ValueError(f"perfiles desconocidos: {unknown}")

    rows: list[dict[str, Any]] = []
    for repeat in range(1, repeats + 1):
        for name in scenarios:
            print(f"[repetición {repeat}/{repeats}] perfil {name}", flush=True)
            rows.extend(
                run_profile(
                    client,
                    build_profile(name),
                    repeat=repeat,
                    latency_budget_ms=latency_budget_ms,
                    cost_budget_usd=cost_budget_usd,
                    on_row=on_row,
                )
            )
        for size in sizes_kb:
            print(f"[repetición {repeat}/{repeats}] adjunto {size} KiB", flush=True)
            row = run_attachment(
                client,
                size_kb=size,
                repeat=repeat,
                latency_budget_ms=latency_budget_ms,
                cost_budget_usd=cost_budget_usd,
            )
            rows.append(row)
            if on_row is not None:
                on_row(row)
    return rows


def write_csv(rows: Sequence[dict[str, Any]], path: Path) -> None:
    """Escribe las filas en un CSV con cabecera :data:`COLUMNS`. Los ``None`` salen como celdas vacías.

    :param rows: Filas producidas por :func:`run_stress`.
    :param path: Ruta de salida; se crean los directorios que falten.
    :raises ValueError: Si una fila tiene claves que no están en :data:`COLUMNS`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row[key] for key in COLUMNS})


def _parse_int_list(text: str) -> list[int]:
    """Convierte ``"0,5,20"`` en ``[0, 5, 20]``, ignorando espacios y elementos vacíos.

    :param text: Lista separada por comas.
    :returns: Los enteros de la lista.
    """
    return [int(item) for item in text.split(",") if item.strip()]


def _parse_names(text: str) -> list[str]:
    """Convierte ``"growing,pivot"`` en ``["growing", "pivot"]``.

    :param text: Lista de nombres separada por comas.
    :returns: Los nombres, sin espacios.
    """
    return [item.strip() for item in text.split(",") if item.strip()]


def build_arg_parser() -> argparse.ArgumentParser:
    """Define los argumentos de línea de órdenes del runner.

    :returns: El parser configurado.
    """
    parser = argparse.ArgumentParser(description="Harness de estrés multi-turno del estimador CAG.")
    parser.add_argument("--http", default=None, help="URL de un servidor en marcha. Sin esta opción se usa TestClient en proceso.")
    parser.add_argument("--scenarios", default=",".join(PROFILE_NAMES), help="Perfiles separados por comas.")
    parser.add_argument("--attachment-sizes", default="0,5,20,50,100", help="Tamaños de adjunto en KiB; 0 es la línea base.")
    parser.add_argument("--repeats", type=int, default=3, help="Repeticiones completas.")
    parser.add_argument("--latency-budget-ms", type=int, default=DEFAULT_LATENCY_BUDGET_MS)
    parser.add_argument("--cost-budget-usd", type=float, default=DEFAULT_COST_BUDGET_USD)
    parser.add_argument("--timeout", type=float, default=120.0, help="Timeout por petición HTTP, en segundos.")
    parser.add_argument("--output", default="evals/stress/results.csv")
    return parser


def _in_process_http() -> Any:
    """Crea un ``TestClient`` sobre la aplicación real. Se importa aquí para no cargar la app en los tests.

    :returns: Un ``fastapi.testclient.TestClient`` con la interfaz de ``httpx.Client``.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def main(argv: Sequence[str] | None = None) -> int:
    """Punto de entrada: ejecuta el harness y escribe el CSV.

    :param argv: Argumentos de línea de órdenes; ``None`` usa ``sys.argv``.
    :returns: 0 si todo fue bien.
    """
    args = build_arg_parser().parse_args(argv)
    http = httpx.Client(base_url=args.http, timeout=args.timeout) if args.http else _in_process_http()
    client = RestStressClient(http)
    output = Path(args.output)
    collected: list[dict[str, Any]] = []

    def checkpoint(row: dict[str, Any]) -> None:
        """Añade la fila y reescribe el CSV, para no perder datos si se interrumpe la ejecución."""
        collected.append(row)
        write_csv(collected, output)

    rows = run_stress(
        client,
        on_row=checkpoint,
        scenarios=_parse_names(args.scenarios),
        sizes_kb=_parse_int_list(args.attachment_sizes),
        repeats=args.repeats,
        latency_budget_ms=args.latency_budget_ms,
        cost_budget_usd=args.cost_budget_usd,
    )
    write_csv(rows, output)
    print(f"{len(rows)} filas escritas en {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
