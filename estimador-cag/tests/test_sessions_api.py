"""Tests de integración de los endpoints de sesión, ejecutados en proceso con ``httpx.AsyncClient``.

El LLM nunca se llama. :meth:`LLMWrapper._dispatch` se sustituye por un doble que
graba los ``messages`` que recibe y devuelve una respuesta determinista. Así los
tests comprueban lo que el servicio *envía* al modelo y cómo guarda la respuesta,
que es la parte que controla este proyecto.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from app.dependencies import get_llm_wrapper, get_session_store
from app.routers import sessions
from app.services.llm_wrapper import LLMWrapper
from app.services.sessions import SessionStore
from tests.sample_data import (
    SAMPLE_ANSWER,
    SAMPLE_PROJECT_NAME,
    TRANSCRIPT_FIRST_TURN,
    TRANSCRIPT_FOLLOW_UP,
    TRANSCRIPT_SHORT,
    make_text_pdf,
)

pytestmark = pytest.mark.anyio

MAX_TURNS = 6


@pytest.fixture
def anyio_backend() -> str:
    """Ejecuta los tests asíncronos de este módulo solo con asyncio."""
    return "asyncio"


def _fake_completion(content: str) -> SimpleNamespace:
    """Construye un objeto con la forma de una respuesta de LiteLLM.

    :param content: Texto que se devuelve como mensaje del asistente.
    :returns: Un ``SimpleNamespace`` con ``choices``, ``usage`` y ``model``.
    """
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        model="gpt-4o-mini",
    )


def _make_wrapper(dispatch) -> LLMWrapper:
    """Crea un :class:`LLMWrapper` real cuya llamada al proveedor se sustituye por ``dispatch``.

    :param dispatch: Función que recibe los argumentos con nombre de la llamada al proveedor.
    :returns: Un wrapper cuya caché siempre falla (no encuentra nada).
    """
    cache = MagicMock()
    cache.get.return_value = None
    wrapper = LLMWrapper(
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
        primary_model="gpt-4o-mini",
        fallback_model="claude-haiku-4-5",
        timeout=5,
        num_retries=0,
        cache=cache,
    )
    wrapper._dispatch = dispatch  # type: ignore[method-assign]
    return wrapper


def _multipart(transcript: str, attachments: tuple[tuple[str, bytes, str], ...] = ()) -> list:
    """Construye el argumento ``files=`` de httpx para que la petición se envíe como multipart/form-data.

    Una tupla ``(None, valor)`` hace que httpx envíe un campo de formulario normal
    dentro de un cuerpo multipart.

    :param transcript: Valor del campo ``transcript``.
    :param attachments: Tuplas ``(nombre_archivo, contenido, tipo_mime)``.
    :returns: Una lista de tuplas de campo para httpx.
    """
    fields: list = [("transcript", (None, transcript))]
    fields += [("attachments", (name, content, media)) for name, content, media in attachments]
    return fields


def _answer_from_message(user_message: str) -> str:
    """Devuelve la respuesta simulada del modelo para un mensaje del usuario.

    La respuesta es :data:`SAMPLE_ANSWER` con su línea ``Total hours`` a 120 si el
    mensaje menciona SAP y a 64 en caso contrario. El resto de la respuesta no
    cambia, así que el extractor de metadatos ve el mismo equipo y alcance en
    todos los tests.

    :param user_message: Mensaje del usuario tal como se envía al modelo, con el texto de los adjuntos.
    :returns: La estimación en Markdown que devuelve el modelo simulado.
    """
    hours = 120 if "SAP" in user_message else 64
    return SAMPLE_ANSWER.replace("- Total hours: 64", f"- Total hours: {hours}")


@pytest.fixture
def recorded_calls() -> list[dict]:
    """Lista donde la llamada simulada al proveedor guarda los argumentos de cada petición."""
    return []


@pytest.fixture
def store() -> SessionStore:
    """Almacén de sesiones nuevo, con el mismo tamaño de ventana que la configuración por defecto."""
    return SessionStore(max_turns=MAX_TURNS)


@pytest.fixture
def answer_for() -> Callable[[str], str]:
    """Devuelve la función que asocia un mensaje del usuario con la respuesta simulada del modelo."""
    return _answer_from_message


@pytest.fixture
def app_and_client(recorded_calls, store, answer_for):
    """Construye una aplicación solo con el router de sesiones y un LLM simulado que graba las llamadas.

    :returns: La aplicación FastAPI, con sustituciones para el almacén de sesiones y el wrapper.
    """

    def fake_dispatch(*, model_override, **kwargs):
        recorded_calls.append({"model_override": model_override, **kwargs})
        user_message = kwargs["messages"][-1]["content"]
        return _fake_completion(answer_for(user_message))

    wrapper = _make_wrapper(fake_dispatch)
    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_llm_wrapper] = lambda: wrapper
    return app


@pytest.fixture
async def client(app_and_client):
    """Un ``httpx.AsyncClient`` que habla con la aplicación en proceso."""
    transport = httpx.ASGITransport(app=app_and_client)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


async def _new_session(client: httpx.AsyncClient) -> str:
    """Crea una sesión con ``POST /sessions`` y devuelve su identificador."""
    response = await client.post("/sessions")
    assert response.status_code == 201
    return response.json()["session_id"]


# ---------------------------------------------------------------------------
# Creación de sesiones
# ---------------------------------------------------------------------------


async def test_post_sessions_returns_a_uuid_session_id(client: httpx.AsyncClient) -> None:
    """``POST /sessions`` devuelve ``{"session_id": ...}`` con un valor UUID v4."""
    response = await client.post("/sessions")

    assert response.status_code == 201
    session_id = response.json()["session_id"]
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", session_id
    )


async def test_unknown_session_returns_404(client: httpx.AsyncClient) -> None:
    """Estimar o leer una sesión que no existe devuelve 404 y nunca llama al LLM."""
    response = await client.post(
        "/sessions/no-existe/estimate", files=_multipart(TRANSCRIPT_SHORT)
    )
    state = await client.get("/sessions/no-existe")

    assert response.status_code == 404
    assert state.status_code == 404


# ---------------------------------------------------------------------------
# Prueba 1: dos peticiones en una sesión comparten los metadatos del proyecto
# ---------------------------------------------------------------------------


async def test_metadata_is_updated_between_turns_and_reaches_the_second_prompt(
    client: httpx.AsyncClient, recorded_calls: list[dict]
) -> None:
    """Tras el primer turno los metadatos tienen nombre, tecnologías y tamaño de equipo; el segundo turno los recibe."""
    session_id = await _new_session(client)

    first = await client.post(
        f"/sessions/{session_id}/estimate", files=_multipart(TRANSCRIPT_FIRST_TURN)
    )
    assert first.status_code == 200
    assert first.json()["prompt_version"] == "session-v1"

    state = (await client.get(f"/sessions/{session_id}")).json()
    metadata = state["project_metadata"]
    assert metadata["project_name"] == SAMPLE_PROJECT_NAME
    assert {"Python", "FastAPI", "PostgreSQL", "React"} <= set(metadata["mentioned_technologies"])
    assert metadata["assumed_team_size"] == 3
    assert state["turns"] == 1

    second = await client.post(
        f"/sessions/{session_id}/estimate", files=_multipart(TRANSCRIPT_FOLLOW_UP)
    )
    assert second.status_code == 200

    first_system = recorded_calls[0]["messages"][0]["content"]
    second_system = recorded_calls[1]["messages"][0]["content"]
    assert "<project_metadata>" not in first_system
    assert f"- Project name: {SAMPLE_PROJECT_NAME}" in second_system
    assert "- Assumed team size: 3 people" in second_system

    second_messages = recorded_calls[1]["messages"]
    assert second_messages[1]["role"] == "user"
    assert second_messages[1]["content"] == TRANSCRIPT_FIRST_TURN
    assert second_messages[2]["role"] == "assistant"
    assert second_messages[-1]["content"] == TRANSCRIPT_FOLLOW_UP


# ---------------------------------------------------------------------------
# Prueba 2: un adjunto PDF cambia un campo concreto de la salida
# ---------------------------------------------------------------------------


def _hours_from(text: str) -> int:
    """Lee el número que aparece tras ``Total hours:`` en una estimación."""
    match = re.search(r"Total hours:\s*(\d+)", text)
    assert match is not None
    return int(match.group(1))


async def test_pdf_attachment_changes_the_total_hours(
    client: httpx.AsyncClient,
    recorded_calls: list[dict],
) -> None:
    """Con un PDF que menciona una integración adicional, cambian las horas totales de la respuesta.

    El modelo simulado responde ``Total hours: 120`` si el requisito de SAP está en el
    mensaje y ``64`` si no. Es un sustituto determinista del modelo real: comprueba que
    el texto del adjunto llega al prompt y que un campo concreto de la salida depende
    de él. No mide la calidad de la estimación real.
    """
    pdf = make_text_pdf(
        [
            "Requisitos adicionales del cliente",
            "Integración con SAP para facturación automática (fase 2)",
        ]
    )

    plain_session = await _new_session(client)
    plain = await client.post(
        f"/sessions/{plain_session}/estimate", files=_multipart(TRANSCRIPT_SHORT)
    )

    pdf_session = await _new_session(client)
    with_pdf = await client.post(
        f"/sessions/{pdf_session}/estimate",
        files=_multipart(
            TRANSCRIPT_SHORT,
            attachments=(("requisitos.pdf", pdf, "application/pdf"),),
        ),
    )

    assert plain.status_code == 200
    assert with_pdf.status_code == 200
    user_with_pdf = recorded_calls[1]["messages"][-1]["content"]
    assert "--- attachment: requisitos.pdf ---" in user_with_pdf
    assert "SAP" in user_with_pdf
    assert _hours_from(with_pdf.json()["text"]) != _hours_from(plain.json()["text"])


# ---------------------------------------------------------------------------
# Prueba 3: ocho turnos nunca envían más de MAX_TURNS pares
# ---------------------------------------------------------------------------


async def test_history_sent_to_the_llm_never_exceeds_max_turns(
    client: httpx.AsyncClient, recorded_calls: list[dict]
) -> None:
    """Ocho turnos en una sesión: cada petición lleva como máximo ``MAX_TURNS`` pares de historial."""
    session_id = await _new_session(client)

    for number in range(1, 9):
        response = await client.post(
            f"/sessions/{session_id}/estimate",
            files=_multipart(f"Turno {number}: añade un informe mensual de rotación de stock."),
        )
        assert response.status_code == 200

    assert len(recorded_calls) == 8
    for call in recorded_calls:
        history_messages = len(call["messages"]) - 2  # quitar el system y el mensaje nuevo del usuario
        assert history_messages <= 2 * MAX_TURNS
        assert history_messages % 2 == 0

    last_messages = recorded_calls[-1]["messages"]
    assert len(last_messages) == 2 * MAX_TURNS + 2
    assert last_messages[1]["content"].startswith("Turno 2:")
    state = (await client.get(f"/sessions/{session_id}")).json()
    assert state["turns"] == MAX_TURNS


# ---------------------------------------------------------------------------
# Validación de adjuntos
# ---------------------------------------------------------------------------


async def test_unsupported_attachment_is_rejected_with_422(
    client: httpx.AsyncClient, recorded_calls: list[dict]
) -> None:
    """Un adjunto con extensión no admitida se rechaza antes de llamar al LLM."""
    session_id = await _new_session(client)

    response = await client.post(
        f"/sessions/{session_id}/estimate",
        files=_multipart(
            TRANSCRIPT_SHORT,
            attachments=(("plano.dwg", b"binary", "application/octet-stream"),),
        ),
    )

    assert response.status_code == 422
    assert recorded_calls == []


async def test_missing_transcript_is_rejected_with_422(client: httpx.AsyncClient) -> None:
    """El campo ``transcript`` es obligatorio y no puede estar vacío."""
    session_id = await _new_session(client)

    response = await client.post(
        f"/sessions/{session_id}/estimate", files=_multipart("")
    )

    assert response.status_code == 422


async def test_llm_failure_returns_500_and_keeps_the_history_unchanged(
    store: SessionStore,
) -> None:
    """Un error del proveedor se convierte en HTTP 500 y no añade ningún turno a la sesión."""

    def failing_dispatch(**_kwargs):
        raise RuntimeError("provider down")

    wrapper = _make_wrapper(failing_dispatch)
    app = FastAPI()
    app.include_router(sessions.router)
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_llm_wrapper] = lambda: wrapper
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as failing_client:
        session_id = (await failing_client.post("/sessions")).json()["session_id"]
        response = await failing_client.post(
            f"/sessions/{session_id}/estimate", files=_multipart(TRANSCRIPT_SHORT)
        )

    assert response.status_code == 500
    assert "provider down" in response.json()["detail"]
    assert store.get(session_id).history.turn_count == 0
