"""Tests for the optional ``reference_projects`` field and its template loop.

The data below is synthetic test data. Nothing here calls an LLM. The tests
check only what the rendered prompts contain.

Run from the repository root with: python -m pytest app/tests/prompts
"""

import pytest
from pydantic import ValidationError

from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
    ReferenceProject,
)

SAMPLE_DESCRIPTION = (
    "Internal tool to manage employee equipment loans (laptops, headsets) with "
    "role-based access for HR and IT and a full audit trail of every loan."
)

REFERENCE_PROJECTS = [
    {
        "name": "Inventory platform",
        "description": "Stock tracking web app for a warehouse with CSV import.",
        "total_cost_eur": 12500,
        "duration_weeks": 10,
    },
    {
        "name": "Lead capture landing",
        "description": "Responsive landing page with CRM sync.",
    },
]


def _request(**overrides) -> EstimationRequest:
    """Build a valid estimation request, applying any field overrides."""
    payload = {
        "description": SAMPLE_DESCRIPTION,
        "project_type": ProjectType.INTERNAL_TOOL,
        "detail_level": DetailLevel.MEDIUM,
        "output_format": OutputFormat.PHASES_TABLE,
    }
    payload.update(overrides)
    return EstimationRequest(**payload)


def _user_prompt(request: EstimationRequest) -> str:
    """Return only the rendered user prompt for ``request`` (v1)."""
    _, user = render_estimation_prompt(request)
    return user


def test_reference_projects_default_to_none() -> None:
    """Omitting the field leaves ``reference_projects`` as ``None``."""
    assert _request().reference_projects is None


def test_user_prompt_without_references_is_unchanged() -> None:
    """Without references the user prompt matches the original template output exactly."""
    expected = (
        f"<project_description>\n{SAMPLE_DESCRIPTION}\n</project_description>\n"
        "\n"
        "Project type: internal_tool.\n"
        "Estimate this project following the rules above."
    )

    assert _user_prompt(_request(reference_projects=None)) == expected


def test_empty_list_renders_no_block() -> None:
    """An empty list is treated like ``None``: no ``<reference_projects>`` block."""
    user = _user_prompt(_request(reference_projects=[]))

    assert "<reference_projects>" not in user
    assert user == _user_prompt(_request())


def test_each_reference_project_is_rendered_in_order() -> None:
    """Every reference project gets one bullet, in the order they were sent."""
    user = _user_prompt(_request(reference_projects=REFERENCE_PROJECTS))

    assert "<reference_projects>" in user
    assert "</reference_projects>" in user
    assert user.index("- Inventory platform:") < user.index("- Lead capture landing:")


def test_optional_figures_only_rendered_when_present() -> None:
    """Cost and duration appear only for the project that provides them."""
    user = _user_prompt(_request(reference_projects=REFERENCE_PROJECTS))
    items = [line for line in user.splitlines() if line.startswith("- ")]

    assert items == [
        "- Inventory platform: Stock tracking web app for a warehouse with CSV import. "
        "Total cost: 12500 EUR. Duration: 10 weeks.",
        "- Lead capture landing: Responsive landing page with CRM sync.",
    ]


def test_block_sits_between_description_and_project_type() -> None:
    """The reference block comes after the description and before the project type line."""
    user = _user_prompt(_request(reference_projects=REFERENCE_PROJECTS))

    assert user.index("</project_description>") < user.index("<reference_projects>")
    assert user.index("</reference_projects>") < user.index("Project type: internal_tool.")


def test_block_is_only_in_user_message() -> None:
    """Reference projects are per-request data, so they stay out of the system prompt."""
    system, user = render_estimation_prompt(_request(reference_projects=REFERENCE_PROJECTS))

    assert "<reference_projects>" in user
    assert "<reference_projects>" not in system
    assert "Inventory platform" not in system


def test_special_characters_are_not_escaped() -> None:
    """Names and descriptions reach the prompt verbatim, as the description does."""
    special = [{"name": 'ACME "Portal" & SSO', "description": "<b>login</b> flow"}]

    user = _user_prompt(_request(reference_projects=special))

    assert '- ACME "Portal" & SSO: <b>login</b> flow' in user


@pytest.mark.parametrize(
    "invalid_project",
    [
        {"name": "", "description": "Valid description."},
        {"name": "Valid name", "description": ""},
        {"name": "Negative cost", "description": "x", "total_cost_eur": -1},
        {"name": "Zero weeks", "description": "x", "duration_weeks": 0},
    ],
)
def test_invalid_reference_project_is_rejected(invalid_project: dict) -> None:
    """Empty text and out-of-range figures fail validation."""
    with pytest.raises(ValidationError):
        ReferenceProject(**invalid_project)


def test_more_than_ten_reference_projects_rejected() -> None:
    """The list is capped at ten entries to keep the prompt size bounded."""
    eleven = [{"name": f"Project {i}", "description": "Example."} for i in range(11)]

    with pytest.raises(ValidationError):
        _request(reference_projects=eleven)
