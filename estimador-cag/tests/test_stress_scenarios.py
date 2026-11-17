"""Tests de los perfiles multi-turno y de su fact-tracker. Datos fijos, sin LLM."""

from __future__ import annotations

import pytest

from evals.stress.scenarios import (
    ATTACHMENT_MARKERS,
    MAX_PROFILE_TURNS,
    PROFILE_NAMES,
    build_profile,
)


@pytest.mark.parametrize("name", PROFILE_NAMES)
def test_every_profile_has_twenty_turns(name):
    scenario = build_profile(name)

    assert len(scenario.transcripts) == MAX_PROFILE_TURNS
    assert all(text.strip() for text in scenario.transcripts)


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="perfil desconocido"):
        build_profile("inexistente")


def test_growing_profile_declares_project_name_at_turn_one():
    scenario = build_profile("growing")

    assert scenario.transcripts[0].startswith("Proyecto: Gestor de inventario para almacén.")
    name_fact = scenario.facts[0]
    assert name_fact.turn == 1
    assert name_fact.text == "Gestor de inventario para almacén"
    assert name_fact.where == ("metadata",)


def test_pivot_profile_switches_from_react_to_flutter_at_turn_five():
    scenario = build_profile("pivot")

    assert "React" in scenario.transcripts[0]
    assert "Flutter" in scenario.transcripts[4]
    react = next(f for f in scenario.facts if f.text == "React")
    assert react.turn == 5
    assert react.should_persist is False


def test_contradiction_profile_marks_thirty_k_as_superseded_by_eighty_k():
    scenario = build_profile("contradiction")

    assert "30k€" in scenario.transcripts[2]
    assert "80k€" in scenario.transcripts[7]
    superseded = [f for f in scenario.facts if not f.should_persist]
    assert [(f.text, f.turn) for f in superseded] == [("30k€", 8)]
    assert any(f.text == "80k€" and f.should_persist for f in scenario.facts)


def test_facts_due_at_excludes_the_declaring_turn_itself():
    scenario = build_profile("growing")

    assert scenario.facts_due_at(1) == ()
    due_at_two = {f.text for f in scenario.facts_due_at(2)}
    assert "Gestor de inventario para almacén" in due_at_two


def test_superseded_facts_only_count_after_their_turn():
    scenario = build_profile("pivot")

    assert scenario.superseded_due_at(5) == ()
    assert [f.text for f in scenario.superseded_due_at(6)] == ["React"]


def test_attachment_markers_are_two_distinct_ascii_tokens():
    assert len(set(ATTACHMENT_MARKERS)) == 2
    assert all(marker.isascii() for marker in ATTACHMENT_MARKERS)
