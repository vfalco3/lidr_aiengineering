"""Tests del runner con un cliente falso. No hay red ni LLM: el falso simula el servicio."""

from __future__ import annotations

import csv
from pathlib import Path

import httpx
import pytest

from evals.stress.run import COLUMNS, RestStressClient, run_attachment, run_stress, write_csv
from evals.stress.scenarios import ATTACHMENT_MARKERS, MAX_PROFILE_TURNS


class FakeService:
    """Servicio simulado: cada turno cuesta 0.001 USD, la latencia es fija y los
    adjuntos hacen que la respuesta contenga los marcadores."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.estimate_calls: list[tuple[str, str, list[str]]] = []

    def create_session(self) -> str:
        session_id = f"s{len(self.sessions) + 1}"
        self.sessions[session_id] = {"turns": 0, "observation": None}
        return session_id

    def estimate(self, session_id, transcript, attachments):
        session = self.sessions[session_id]
        session["turns"] += 1
        session["observation"] = {
            "turn_index": session["turns"],
            "session_id": session_id,
            "enriched_transcript_chars": len(transcript),
            "attachments_total_chars": 10 if attachments else 0,
            "messages_in_window": min(2 * session["turns"], 12),
            "anchors_count": 0,
            "summary_chars": 0,
            "tokens_in": 1000 + 10 * session["turns"],
            "tokens_out": 200,
            "cost_usd": 0.001,
            "latency_ms": 100 + session["turns"],
            "cache_hit_kind": "none",
            "last_resolved_tier": None,
        }
        self.estimate_calls.append((session_id, transcript, [name for name, _ in attachments]))
        markers = " ".join(ATTACHMENT_MARKERS) if attachments else ""
        return f"## Proyecto\n{markers}".strip()

    def state(self, session_id):
        session = self.sessions[session_id]
        return {
            "session_id": session_id,
            "turns": session["turns"],
            "project_metadata": {"project_name": "Demo", "mentioned_technologies": ["Python"]},
            "last_turn_observation": session["observation"],
        }


def test_profile_rows_match_columns_and_one_row_per_turn():
    rows = run_stress(FakeService(), scenarios=["growing"], sizes_kb=[], repeats=1)

    assert len(rows) == MAX_PROFILE_TURNS
    assert set(rows[0]) == set(COLUMNS)
    assert [row["turn_index"] for row in rows] == list(range(1, MAX_PROFILE_TURNS + 1))


def test_first_turn_has_no_drift_score_and_later_turns_do():
    rows = run_stress(FakeService(), scenarios=["growing"], sizes_kb=[], repeats=1)

    assert rows[0]["memory_drift_score"] is None
    assert rows[1]["memory_drift_score"] in (0.0, 1.0)


def test_cumulative_cost_grows_by_each_turn_cost():
    rows = run_stress(FakeService(), scenarios=["pivot"], sizes_kb=[], repeats=1)

    cumulative = [row["cumulative_cost_usd"] for row in rows]
    assert cumulative == sorted(cumulative)
    assert cumulative[-1] == pytest.approx(0.001 * MAX_PROFILE_TURNS)


def test_superseded_fact_presence_is_reported_as_stale():
    service = FakeService()
    rows = run_stress(service, scenarios=["pivot"], sizes_kb=[], repeats=1)

    stale_values = {row["turn_index"]: row["stale_present"] for row in rows}
    assert stale_values[5] is None
    assert stale_values[6] in (0, 1)


def test_first_transcript_carries_a_repeat_nonce_to_avoid_cache_hits():
    service = FakeService()
    run_stress(service, scenarios=["growing"], sizes_kb=[], repeats=2)

    first_turns = [call[1] for call in service.estimate_calls if "[ejecución growing-" in call[1]]
    assert any("-r1] " in text for text in first_turns)
    assert any("-r2] " in text for text in first_turns)


def test_attachment_baseline_has_no_recall_and_sized_runs_have_full_recall():
    rows = run_stress(FakeService(), scenarios=[], sizes_kb=[0, 5], repeats=1)

    baseline, sized = rows
    assert baseline["attachment_kb"] == 0
    assert baseline["marker_recall"] is None
    assert sized["attachment_kb"] == 5
    assert sized["marker_recall"] == 1.0


def test_attachment_sends_pdf_with_expected_filename():
    service = FakeService()
    run_attachment(service, size_kb=5, repeat=1, latency_budget_ms=4000, cost_budget_usd=0.01)

    _, _, names = service.estimate_calls[0]
    assert names == ["requisitos.pdf"]


def test_budget_flags_follow_the_limits():
    rows = run_stress(
        FakeService(),
        scenarios=[],
        sizes_kb=[5],
        repeats=1,
        latency_budget_ms=50,
        cost_budget_usd=0.01,
    )

    assert rows[0]["latency_budget_ok"] == 0
    assert rows[0]["cost_budget_ok"] == 1


def test_invalid_arguments_are_rejected():
    with pytest.raises(ValueError, match="repeats"):
        run_stress(FakeService(), scenarios=[], sizes_kb=[], repeats=0)
    with pytest.raises(ValueError, match="perfiles desconocidos"):
        run_stress(FakeService(), scenarios=["nope"], sizes_kb=[], repeats=1)


def test_write_csv_writes_header_and_blank_cells_for_none(tmp_path: Path):
    rows = run_stress(FakeService(), scenarios=["growing"], sizes_kb=[0], repeats=1)
    output = tmp_path / "nested" / "results.csv"

    write_csv(rows, output)

    with output.open(newline="", encoding="utf-8") as handle:
        reader = list(csv.DictReader(handle))
    assert reader[0].keys() == set(COLUMNS)
    assert len(reader) == MAX_PROFILE_TURNS + 1
    assert reader[0]["memory_drift_score"] == ""
    assert reader[-1]["scenario"] == "attachment"


def test_rest_client_posts_multipart_and_reads_state():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST" and request.url.path == "/sessions":
            return httpx.Response(201, json={"session_id": "abc"})
        if request.method == "POST" and request.url.path == "/sessions/abc/estimate":
            return httpx.Response(200, json={"text": "ok", "prompt_version": "session-v1"})
        if request.method == "GET" and request.url.path == "/sessions/abc":
            return httpx.Response(200, json={"session_id": "abc", "last_turn_observation": None})
        return httpx.Response(404)

    http = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    client = RestStressClient(http)

    session_id = client.create_session()
    text = client.estimate(session_id, "hola", [("requisitos.pdf", b"%PDF-1.4 fake")])
    state = client.state(session_id)

    assert session_id == "abc"
    assert text == "ok"
    assert state["session_id"] == "abc"
    estimate_request = seen[1]
    assert estimate_request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="transcript"' in estimate_request.content
    assert b'filename="requisitos.pdf"' in estimate_request.content


def test_rest_client_raises_on_http_error():
    http = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    with pytest.raises(httpx.HTTPStatusError):
        RestStressClient(http).create_session()


def test_on_row_receives_every_row_in_order():
    received: list[dict] = []

    rows = run_stress(
        FakeService(),
        scenarios=["growing"],
        sizes_kb=[0, 5],
        repeats=1,
        on_row=received.append,
    )

    assert len(received) == len(rows) == MAX_PROFILE_TURNS + 2
    assert [row["turn_index"] for row in received[:MAX_PROFILE_TURNS]] == list(range(1, MAX_PROFILE_TURNS + 1))
    assert received[-1]["scenario"] == "attachment"
