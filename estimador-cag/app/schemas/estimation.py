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
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"


class DetailLevel(str, Enum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"


class OutputFormat(str, Enum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"


# Output formats for the few-shot reference examples injected into the prompt.
# Used by app/context/examples.py to select the rendering function.
ExampleFormat = Literal["markdown", "json", "narrative"]


class EstimationRequest(BaseModel):
    """Typed payload sent by the business backend or Streamlit form."""

    description: str = Field(
        min_length=20,
        max_length=80000,
        description="Free-text description or transcription of the project to estimate.",
    )
    project_type: ProjectType = Field(description="Coarse-grained project category.")
    detail_level: DetailLevel = Field(description="How deep the estimation should go.")
    output_format: OutputFormat = Field(description="Shape of the rendered estimation.")


class EstimationResponse(BaseModel):
    """Estimation rendered as free text, plus the prompt version that produced it."""

    text: str = Field(description="Estimation rendered by the LLM as free text.")
    prompt_version: str = Field(description="Identifier of the prompt template used.")