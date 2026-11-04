"""Template-level tests for the ``estimation/v1`` prompt.

These tests exercise only the Jinja2 rendering done by
``app.prompts.loader.render_estimation_prompt``. They do not call any LLM and
do not touch the network, so they run in milliseconds. They check what the
rendered prompt contains, not the quality of the model output.

Run from the repository root with: python -m pytest app/tests/prompts
"""

import pytest

from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)

SAMPLE_DESCRIPTION = (
    "Internal tool to manage employee equipment loans (laptops, headsets) with "
    "role-based access for HR and IT and a full audit trail of every loan."
)

# Characters that Jinja2 would escape if autoescape were enabled. The loader
# disables autoescape, so the description must reach the prompt untouched.
SPECIAL_CHARS_DESCRIPTION = (
    'Portal "ACME" & partners: <b>login</b> flow, SSO via SAML, '
    "3 roles (50% discount for NGOs)."
)


def _make_request(
    description: str = SAMPLE_DESCRIPTION,
    output_format: OutputFormat = OutputFormat.PHASES_TABLE,
    detail_level: DetailLevel = DetailLevel.MEDIUM,
) -> EstimationRequest:
    """Build a valid estimation request for the tests, with sensible defaults."""
    return EstimationRequest(
        description=description,
        project_type=ProjectType.INTERNAL_TOOL,
        detail_level=detail_level,
        output_format=output_format,
    )


def test_user_prompt_contains_description_literally_inside_tag():
    """The description is embedded verbatim inside the project_description tag.

    Uses a description with HTML-like and quote characters to confirm that no
    escaping is applied during rendering.
    """
    _, user = render_estimation_prompt(
        _make_request(description=SPECIAL_CHARS_DESCRIPTION)
    )

    expected_block = (
        f"<project_description>\n{SPECIAL_CHARS_DESCRIPTION}\n</project_description>"
    )
    assert expected_block in user


@pytest.mark.parametrize(
    ("output_format", "expected_in_system"),
    [
        (OutputFormat.PHASES_TABLE, True),
        (OutputFormat.LINE_ITEMS, False),
        (OutputFormat.NARRATIVE, False),
    ],
)
def test_phases_table_keyword_only_rendered_for_phases_table(
    output_format: OutputFormat,
    expected_in_system: bool,
) -> None:
    """The phases_table keyword appears in the system prompt only for that format.

    confidence_pct is deliberately not used here: the shared examples include
    always renders it in its table headers, so it cannot tell formats apart.
    """
    system, _ = render_estimation_prompt(_make_request(output_format=output_format))

    assert ("phases_table" in system) is expected_in_system


@pytest.mark.parametrize(
    ("detail_level", "expected_in_system"),
    [
        (DetailLevel.DETAILED, True),
        (DetailLevel.MEDIUM, False),
        (DetailLevel.SUMMARY, False),
    ],
)
def test_assumptions_per_phase_instruction_only_for_detailed(
    detail_level: DetailLevel,
    expected_in_system: bool,
) -> None:
    """The per-phase assumptions instruction is rendered only for the detailed level."""
    system, _ = render_estimation_prompt(_make_request(detail_level=detail_level))

    assert ("assumptions per phase" in system) is expected_in_system
