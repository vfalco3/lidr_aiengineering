import structlog

from app.config import get_settings
from app.context.examples import ESTIMATION_EXAMPLES, format_examples_for_prompt

log = structlog.get_logger()
settings = get_settings()

MAX_TOKENS=3000

class LLMServiceError(Exception):
    """ERROR LLM"""

def build_system_prompt() -> str:
    """Construct the system prompt with role definition and reference examples."""
    examples_text = format_examples_for_prompt(ESTIMATION_EXAMPLES)
    system_prompt = (
        "Act as a senior software consultant with more than 15 years of experience in "
        "project estimation. Your job is to write a detailed software project estimate from "
        "a meeting transcription supplied by the user.\n\n"
        "The reference estimates below come from earlier projects. Use them to guide the "
        "structure, the level of detail and the pricing, and adjust the content to fit the "
        "project described in the transcription.\n\n"
        "Your answer MUST follow this exact format:\n"
        "- Project title as an H2 heading\n"
        "- A task breakdown table with columns: Task, Hours, Cost (EUR)\n"
        "- Total hours\n"
        "- Total cost in EUR\n"
        "- Recommended team composition\n"
        "- Estimated duration in weeks\n\n"
        "Apply a developer rate of about 42.50 EUR per hour (340 EUR per day) and a designer "
        "rate of about 35 EUR per hour (280 EUR per day). Give realistic numbers and make sure "
        "each one is justified.\n\n"
        f"{examples_text}"
    )
    return system_prompt

def generate_estimation(transcription: str) -> dict:
    """Generate a software estimation from a meeting transcription using the configured LLM."""
    settings = get_settings()
    system_prompt = build_system_prompt()

    log.info("generating_estimation", provider=settings.LLM_PROVIDER, model=settings.LLM_MODEL)

    try:
       return _call_anthropic(system=system_prompt, user_message=transcription)
    except LLMServiceError:
        raise
    except Exception as exc:
        log.error("llm_call_failed", error=str(exc), provider=settings.LLM_PROVIDER)
        raise LLMServiceError(f"LLM call failed: {exc}") from exc


def _call_anthropic(system: str, user_message: str) -> dict:
    """Send a message request to the Anthropic API."""
    from anthropic import Anthropic

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )

    log.info(
        "llm_response_received",
        provider="anthropic",
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )

    return {
        "estimation": response.content[0].text,
        "model": response.model,
        "provider": "anthropic",
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        },
    }