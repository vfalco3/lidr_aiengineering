"""Tests for the ``prompt_rendered`` structlog event and version validation.

The events are captured in memory with ``structlog.testing.capture_logs``. No
LLM is called and no network is used. The request data is synthetic.

Run from the repository root with: python -m pytest app/tests/prompts
"""

import hashlib
import re

import pytest
from structlog.testing import capture_logs

from app.prompts.loader import (
    SUPPORTED_PROMPT_VERSIONS,
    UnknownPromptVersionError,
    render_estimation_prompt,
)
from app.schemas.estimation import (
    DetailLevel,
    EstimationRequest,
    OutputFormat,
    ProjectType,
)

DESCRIPTION_A = (
    "Internal tool to manage employee equipment loans (laptops, headsets) with "
    "role-based access for HR and IT and a full audit trail of every loan."
)
DESCRIPTION_B = (
    "Customer portal for a regional utility: meter readings, invoice downloads, "
    "payment by card and a support ticket form for billing questions."
)
HEX16 = re.compile(r"^[0-9a-f]{16}$")


def _request(description: str = DESCRIPTION_A, **overrides) -> EstimationRequest:
    """Build a valid estimation request, applying any field overrides."""
    payload = {
        "description": description,
        "project_type": ProjectType.INTERNAL_TOOL,
        "detail_level": DetailLevel.MEDIUM,
        "output_format": OutputFormat.PHASES_TABLE,
    }
    payload.update(overrides)
    return EstimationRequest(**payload)


def _rendered_events(logs: list[dict]) -> list[dict]:
    """Keep only the ``prompt_rendered`` events from a captured log list."""
    return [entry for entry in logs if entry["event"] == "prompt_rendered"]


def test_render_emits_one_event_with_version_and_use_case() -> None:
    """A render emits exactly one ``prompt_rendered`` event carrying the version."""
    with capture_logs() as logs:
        render_estimation_prompt(_request(), version="v1")

    events = _rendered_events(logs)
    assert len(events) == 1
    assert events[0]["prompt_version"] == "v1"
    assert events[0]["use_case"] == "estimation"


def test_hashes_are_sha256_prefixes_of_the_rendered_prompts() -> None:
    """The logged hashes are the first 16 hex characters of SHA-256 over each prompt."""
    with capture_logs() as logs:
        system, user = render_estimation_prompt(_request(), version="v2")

    event = _rendered_events(logs)[0]
    assert event["system_hash"] == hashlib.sha256(system.encode("utf-8")).hexdigest()[:16]
    assert event["user_hash"] == hashlib.sha256(user.encode("utf-8")).hexdigest()[:16]
    assert HEX16.match(event["system_hash"])
    assert HEX16.match(event["user_hash"])


def test_same_request_gives_identical_hashes() -> None:
    """Rendering the same request twice produces the same logged hashes."""
    with capture_logs() as logs:
        render_estimation_prompt(_request(), version="v1")
        render_estimation_prompt(_request(), version="v1")

    first, second = _rendered_events(logs)
    assert first["system_hash"] == second["system_hash"]
    assert first["user_hash"] == second["user_hash"]


def test_changed_description_changes_only_the_user_hash() -> None:
    """The system prompt does not contain the description, so only the user hash moves."""
    with capture_logs() as logs:
        render_estimation_prompt(_request(DESCRIPTION_A), version="v1")
        render_estimation_prompt(_request(DESCRIPTION_B), version="v1")

    first, second = _rendered_events(logs)
    assert first["system_hash"] == second["system_hash"]
    assert first["user_hash"] != second["user_hash"]


def test_reference_projects_change_only_the_user_hash() -> None:
    """Adding reference projects alters the user prompt but not the system prompt."""
    references = [{"name": "Inventory platform", "description": "Warehouse web app."}]
    with capture_logs() as logs:
        render_estimation_prompt(_request(), version="v1")
        render_estimation_prompt(_request(reference_projects=references), version="v1")

    without, with_refs = _rendered_events(logs)
    assert without["system_hash"] == with_refs["system_hash"]
    assert without["user_hash"] != with_refs["user_hash"]


def test_v1_and_v2_produce_different_system_hashes() -> None:
    """Each prompt version is distinguishable in the logs by its system hash."""
    with capture_logs() as logs:
        render_estimation_prompt(_request(), version="v1")
        render_estimation_prompt(_request(), version="v2")

    v1_event, v2_event = _rendered_events(logs)
    assert v1_event["prompt_version"] == "v1"
    assert v2_event["prompt_version"] == "v2"
    assert v1_event["system_hash"] != v2_event["system_hash"]


@pytest.mark.parametrize("bad_version", ["v3", "../v1", "V1", ""])
def test_unknown_version_raises_and_logs_nothing(bad_version: str) -> None:
    """An unsupported version is rejected before any template is read or logged."""
    with capture_logs() as logs, pytest.raises(UnknownPromptVersionError):
        render_estimation_prompt(_request(), version=bad_version)

    assert _rendered_events(logs) == []


def test_supported_versions_are_v1_and_v2() -> None:
    """The supported versions are derived from the schema Literal and list both variants."""
    assert SUPPORTED_PROMPT_VERSIONS == ("v1", "v2")
