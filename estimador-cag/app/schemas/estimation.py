"""Request and response models for the estimation endpoint.

The Session 4 contract is intentionally narrow: a typed form-style request
(description plus three categorical knobs) maps to a free-text response. The
output stays opaque on purpose; structured output, guardrails and semantic
caching land in later sessions.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ProjectType(str, Enum):
    """Coarse-grained project category sent with every estimation request."""

    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"


class DetailLevel(str, Enum):
    """How deep the rendered estimation should go."""

    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"


class OutputFormat(str, Enum):
    """Shape of the rendered estimation."""

    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"


# Output formats for the few-shot reference examples injected into the prompt.
# Used by app/context/examples.py to select the rendering function.
ExampleFormat = Literal["markdown", "json", "narrative"]

# Preprocessing modes understood by app/services/llm_service.py.
PreprocessingMode = Literal["none", "inline_cleaning", "two_phase"]

#: Prompt template versions accepted by the estimation endpoint. Each value is
#: a directory under ``app/prompts/estimation/``. The loader rejects any value
#: not listed here, so user input never reaches the filesystem loader directly.
PromptVersion = Literal["v1", "v2"]


class ReferenceProject(BaseModel):
    """A past project offered as calibration context for the estimation.

    The figures are optional. They are rendered only when present, so a
    project with just a name and a description is still valid.
    """

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Short name of the past project.",
    )
    description: str = Field(
        min_length=1,
        max_length=2000,
        description="What the past project delivered, in a few sentences.",
    )
    total_cost_eur: int | None = Field(
        default=None,
        ge=0,
        description="Total cost of the past project in EUR, if known.",
    )
    duration_weeks: int | None = Field(
        default=None,
        ge=1,
        description="Calendar duration of the past project in weeks, if known.",
    )


class EstimationRequest(BaseModel):
    """Typed payload sent by the business backend or Streamlit form.

    :ivar reference_projects: Optional list of past projects used as calibration
        context. When ``None`` or empty, the user prompt is rendered without the
        ``<reference_projects>`` block.
    """

    description: str = Field(
        min_length=20,
        max_length=80000,
        description="Free-text description or transcription of the project to estimate.",
    )
    project_type: ProjectType = Field(description="Coarse-grained project category.")
    detail_level: DetailLevel = Field(description="How deep the estimation should go.")
    output_format: OutputFormat = Field(description="Shape of the rendered estimation.")
    reference_projects: list[ReferenceProject] | None = Field(
        default=None,
        max_length=10,
        description="Optional past projects to use as calibration context.",
    )


class StreamEstimationRequest(BaseModel):
    """Payload for the streaming endpoint, which takes a raw meeting transcription.

    The streaming path skips the typed form fields on purpose; see
    :func:`app.routers.estimations.create_estimation_stream`.
    """

    transcription: str = Field(
        min_length=1,
        max_length=80000,
        description="Raw meeting transcription or free-text project notes.",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override for this request.",
    )
    max_tokens: int = Field(
        default=4000,
        ge=1,
        le=8000,
        description="Maximum number of output tokens.",
    )


class EstimationResponse(BaseModel):
    """Estimation rendered as free text, plus the prompt version that produced it."""

    text: str = Field(description="Estimation rendered by the LLM as free text.")
    prompt_version: str = Field(description="Identifier of the prompt template used.")
