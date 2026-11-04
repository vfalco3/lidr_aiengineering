import asyncio
from collections.abc import AsyncIterator

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.dependencies import get_llm_wrapper
from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import (
    EstimationRequest,
    EstimationResponse,
    StreamEstimationRequest,
)
from app.services.llm_service import build_system_prompt
from app.services.llm_wrapper import LLMWrapper

log = structlog.get_logger()

PROMPT_VERSION = "v1"
ESTIMATION_MAX_TOKENS = 4000

router = APIRouter(prefix="/api/v1", tags=["estimations"])


@router.post("/estimate", response_model=EstimationResponse)
def create_estimation(
    request: EstimationRequest,
    wrapper: LLMWrapper = Depends(get_llm_wrapper),
) -> EstimationResponse:
    """Render the estimation prompts for a typed request and return the LLM estimation.

    The system and user prompts come from the versioned Jinja2 templates through
    :func:`app.prompts.loader.render_estimation_prompt`. They are sent to the model
    as two separate messages (``role: "system"`` and ``role: "user"``), never
    concatenated into a single message.

    The endpoint is a plain ``def`` so FastAPI runs the blocking LLM call in its
    worker threadpool instead of blocking the event loop.

    The request is the typed estimation payload (description, project type, detail
    level and output format). The shared LLM wrapper is injected by FastAPI through
    ``get_llm_wrapper``. An LLM failure is reported as an HTTP 500 error. On success,
    the model output is returned as free text, tagged with the prompt version used.
    """
    system_prompt, user_prompt = render_estimation_prompt(request, version=PROMPT_VERSION)

    try:
        result = wrapper.complete(
            system_prompt=system_prompt,
            user_message=user_prompt,
            max_tokens=ESTIMATION_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 — any provider failure maps to a 500
        log.error("estimation_endpoint_error", error=str(exc), error_type=type(exc).__name__)
        raise HTTPException(status_code=500, detail=f"LLM call failed: {exc}") from exc

    return EstimationResponse(text=result["estimation"], prompt_version=PROMPT_VERSION)


@router.post("/estimate/stream")
async def create_estimation_stream(
    request: StreamEstimationRequest,
    wrapper: LLMWrapper = Depends(get_llm_wrapper),
) -> EventSourceResponse:
    """Stream a software estimation token by token via Server-Sent Events.

    The streaming path is intentionally simpler than POST /estimate: it skips
    two-phase preprocessing and structural validation, since both fight the UX
    benefit of streaming (intermediate phase 1 tokens would leak; validation
    only makes sense over the complete text).
    """
    system_prompt = build_system_prompt()

    async def event_generator() -> AsyncIterator[dict]:
        loop = asyncio.get_running_loop()
        chunks = wrapper.complete_stream(
            system_prompt=system_prompt,
            user_message=request.transcription,
            model_override=request.model,
            max_tokens=request.max_tokens,
        )

        def _next_chunk() -> str | None:
            try:
                return next(chunks)
            except StopIteration:
                return None
            except Exception as exc:  # noqa: BLE001 — surface as SSE error event
                log.error("estimate_stream_failed", error=str(exc), error_type=type(exc).__name__)
                raise

        try:
            while True:
                chunk = await loop.run_in_executor(None, _next_chunk)
                if chunk is None:
                    break
                if chunk:
                    yield {"event": "token", "data": chunk}
            yield {"event": "done", "data": "[DONE]"}
        except Exception as exc:  # noqa: BLE001
            yield {"event": "error", "data": str(exc)}

    return EventSourceResponse(event_generator())