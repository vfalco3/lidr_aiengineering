"""Tests for the ``estimation/v2`` prompt variant.

v2 differs from v1 on purpose: a reviewer tone, an executive-summary rule, an
unverified-assumptions instruction, and its own reference examples. These tests
check those differences and the consistency of the example figures. They do not
call an LLM.

Run from the repository root with: python -m pytest app/tests/prompts
"""

import re

import pytest

from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)

SAMPLE_DESCRIPTION = (
    "Plataforma web para gestionar el inventario de un almacén con alertas de "
    "stock bajo, importación CSV y un panel de métricas para el responsable."
)

HOURLY_RATE_EUR = 62.5


def _request(
    output_format: OutputFormat = OutputFormat.PHASES_TABLE,
    detail_level: DetailLevel = DetailLevel.MEDIUM,
) -> EstimationRequest:
    """Build a valid estimation request with the given knobs."""
    return EstimationRequest(
        description=SAMPLE_DESCRIPTION,
        project_type=ProjectType.WEB_SAAS,
        detail_level=detail_level,
        output_format=output_format,
    )


def test_v2_system_uses_reviewer_tone() -> None:
    """The v2 system prompt opens with the reviewer persona; v1 does not."""
    system_v2, _ = render_estimation_prompt(_request(), version="v2")
    system_v1, _ = render_estimation_prompt(_request(), version="v1")

    assert "pragmatic estimation reviewer" in system_v2
    assert "pragmatic estimation reviewer" not in system_v1


def test_v2_requires_executive_summary_first() -> None:
    """The v2 rules ask for a two-sentence executive summary before any table."""
    system, _ = render_estimation_prompt(_request(), version="v2")

    assert "Open with a two-sentence executive summary" in system


def test_v2_user_prompt_asks_to_flag_unverified_assumptions() -> None:
    """The v2 user prompt ends with the unverified-assumptions instruction."""
    _, user_v2 = render_estimation_prompt(_request(), version="v2")
    _, user_v1 = render_estimation_prompt(_request(), version="v1")

    assert "Flag any assumption you cannot verify" in user_v2
    assert "Flag any assumption you cannot verify" not in user_v1


def test_v2_uses_its_own_example_set() -> None:
    """v2 shows its data-pipeline and booking examples, not the v1 examples."""
    system, _ = render_estimation_prompt(_request(), version="v2")

    assert "Nightly ingestion of ERP sales exports" in system
    assert "Booking widget SaaS for independent clinics" in system
    assert "employee equipment loans" not in system


def _example_tables(system: str) -> list[str]:
    """Return the Markdown table blocks of the v2 examples, one string per example."""
    blocks = re.split(r"<example>", system)[1:]
    return [block for block in blocks if "| phase" in block]


@pytest.mark.parametrize("table_index", [0, 1])
def test_v2_example_phase_costs_add_up_to_total(table_index: int) -> None:
    """The phase costs in each example sum to the example's stated total cost."""
    system, _ = render_estimation_prompt(_request(), version="v2")
    block = _example_tables(system)[table_index]
    totals = re.search(r"Totals: \d+ total_hours, ([\d,]+) total_cost_eur", block)
    phase_costs = [
        int(cost.replace(",", ""))
        for cost in re.findall(r"^\|\s*[A-Za-z]+\s*\|\s*\d+\s*\|\s*([\d,]+)\s*\|", block, re.M)
    ]

    assert totals is not None
    assert sum(phase_costs) == int(totals.group(1).replace(",", ""))


@pytest.mark.parametrize("table_index", [0, 1])
def test_v2_example_hours_match_total_cost_at_developer_rate(table_index: int) -> None:
    """Total hours times the developer rate equals the total cost in each example."""
    system, _ = render_estimation_prompt(_request(), version="v2")
    block = _example_tables(system)[table_index]
    totals = re.search(r"Totals: (\d+) total_hours, ([\d,]+) total_cost_eur", block)

    assert totals is not None
    hours = int(totals.group(1))
    cost = int(totals.group(2).replace(",", ""))
    assert hours * HOURLY_RATE_EUR == cost


@pytest.mark.parametrize("table_index", [0, 1])
def test_v2_example_durations_add_up_to_total_weeks(table_index: int) -> None:
    """The phase durations in each example sum to the stated total weeks."""
    system, _ = render_estimation_prompt(_request(), version="v2")
    block = _example_tables(system)[table_index]
    total_weeks = int(re.search(r"(\d+) total_duration_weeks", block).group(1))
    weeks = [
        int(duration)
        for duration in re.findall(r"^\|\s*[A-Za-z]+\s*\|\s*(\d+)\s*\|", block, re.M)
    ]

    assert sum(weeks) == total_weeks


@pytest.mark.parametrize("output_format", list(OutputFormat))
def test_v2_output_format_is_rendered_into_system_prompt(output_format: OutputFormat) -> None:
    """Each output format is named in the v2 system prompt."""
    system, _ = render_estimation_prompt(_request(output_format=output_format), version="v2")

    assert f'output_format = "{output_format.value}"' in system


@pytest.mark.parametrize(
    ("output_format", "expected_in_system"),
    [
        (OutputFormat.PHASES_TABLE, True),
        (OutputFormat.LINE_ITEMS, False),
        (OutputFormat.NARRATIVE, False),
    ],
)
def test_v2_phases_table_keyword_only_for_phases_table(
    output_format: OutputFormat,
    expected_in_system: bool,
) -> None:
    """The phases_table layout instruction appears in v2 only for that format."""
    system, _ = render_estimation_prompt(_request(output_format=output_format), version="v2")

    assert ("phases_table" in system) is expected_in_system


@pytest.mark.parametrize(
    ("detail_level", "expected_in_system"),
    [
        (DetailLevel.DETAILED, True),
        (DetailLevel.MEDIUM, False),
        (DetailLevel.SUMMARY, False),
    ],
)
def test_v2_assumptions_per_phase_only_for_detailed(
    detail_level: DetailLevel,
    expected_in_system: bool,
) -> None:
    """The per-phase assumptions instruction is rendered in v2 only for the detailed level."""
    system, _ = render_estimation_prompt(_request(detail_level=detail_level), version="v2")

    assert ("assumptions per phase" in system) is expected_in_system


def test_v2_description_is_only_in_user_message() -> None:
    """The project description travels in the user message in v2 as well."""
    system, user = render_estimation_prompt(_request(), version="v2")

    assert SAMPLE_DESCRIPTION not in system
    assert SAMPLE_DESCRIPTION in user


def test_v2_user_prompt_renders_reference_projects_loop() -> None:
    """The shared reference loop works in v2 too."""
    request = EstimationRequest(
        description=SAMPLE_DESCRIPTION,
        project_type=ProjectType.WEB_SAAS,
        detail_level=DetailLevel.MEDIUM,
        output_format=OutputFormat.PHASES_TABLE,
        reference_projects=[{"name": "Inventory platform", "description": "Warehouse app."}],
    )

    _, user = render_estimation_prompt(request, version="v2")

    assert "- Inventory platform: Warehouse app." in user
