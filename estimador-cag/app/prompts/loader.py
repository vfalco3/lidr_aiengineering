"""Jinja2 loader for versioned prompt templates.

The on-disk layout is ``app/prompts/<use_case>/<version>/<role>.j2``. Versioning
is required from day one: switching prompts becomes a string change at the
call site (``version="v2"``), not a code refactor.

Every successful render emits a ``prompt_rendered`` structlog event with the
prompt version and short SHA-256 digests of the rendered system and user
prompts. Those digests make it possible to tell, in production, which exact
prompt produced a given estimation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import get_args

import structlog
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.schemas.estimation import EstimationRequest, PromptVersion

log = structlog.get_logger()

_BASE_DIR = Path(__file__).resolve().parent

#: Versions accepted by :func:`render_estimation_prompt`, derived from
#: :data:`app.schemas.estimation.PromptVersion` so the two never drift apart.
SUPPORTED_PROMPT_VERSIONS: tuple[str, ...] = get_args(PromptVersion)

_HASH_LENGTH = 16

_env = Environment(
    loader=FileSystemLoader(_BASE_DIR),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
    keep_trailing_newline=True,
)


class UnknownPromptVersionError(ValueError):
    """Raised when a prompt version is not in :data:`SUPPORTED_PROMPT_VERSIONS`.

    The check runs before any template path is built, so a value such as
    ``"../v1"`` never reaches the filesystem loader.
    """


def _short_digest(text: str) -> str:
    """Return a short, log-friendly SHA-256 digest of a rendered prompt.

    :param text: The rendered prompt text, encoded as UTF-8 before hashing.
    :returns: The first 16 lowercase hexadecimal characters of the digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_HASH_LENGTH]


def render_estimation_prompt(
    request: EstimationRequest,
    version: str = "v1",
) -> tuple[str, str]:
    """Render the system and user prompts for the estimation use case.

    The request's ``reference_projects`` list is passed to the templates. The
    templates render the ``<reference_projects>`` block only when the list is
    present and non-empty.

    :param request: Validated estimation request holding the project data.
    :param version: Prompt template version to render. Must be one of
        :data:`SUPPORTED_PROMPT_VERSIONS`. Defaults to ``"v1"``.
    :returns: A tuple ``(system_prompt, user_prompt)`` ready to be sent to the
        LLM as separate ``role: "system"`` and ``role: "user"`` messages.
    :raises UnknownPromptVersionError: If ``version`` is not a supported version.
        Nothing is logged and no template is read in that case.
    """
    if version not in SUPPORTED_PROMPT_VERSIONS:
        raise UnknownPromptVersionError(
            f"Unknown prompt version {version!r}; expected one of {SUPPORTED_PROMPT_VERSIONS}."
        )

    context = {
        "description": request.description,
        "project_type": request.project_type.value,
        "detail_level": request.detail_level.value,
        "output_format": request.output_format.value,
        "reference_projects": request.reference_projects,
    }
    system = _env.get_template(f"estimation/{version}/system.j2").render(**context)
    user = _env.get_template(f"estimation/{version}/user.j2").render(**context)

    log.info(
        "prompt_rendered",
        use_case="estimation",
        prompt_version=version,
        system_hash=_short_digest(system),
        user_hash=_short_digest(user),
    )
    return system, user
