"""Endpoints para las sesiones de estimación de varios turnos.

* ``POST /sessions`` crea una sesión y devuelve su identificador.
* ``GET /sessions/{session_id}`` devuelve los metadatos del proyecto y el número de
  turnos. El panel del cliente Streamlit lo usa para mostrar lo que el modelo sabe.
* ``POST /sessions/{session_id}/estimate`` recibe un cuerpo ``multipart/form-data``
  con un campo ``transcript`` y ``attachments`` opcionales, y devuelve un
  :class:`~app.schemas.estimation.EstimationResponse`.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.dependencies import get_llm_wrapper, get_session_store
from app.prompts.loader import render_session_system_prompt
from app.routers.estimations import ESTIMATION_MAX_TOKENS
from app.schemas.estimation import EstimationResponse
from app.services.attachments import AttachmentError, build_transcript_with_attachments, extract_text
from app.services.llm_wrapper import LLMWrapper
from app.services.metadata_extractor import update_metadata
from app.services.sessions import ProjectMetadata, SessionStore

log = structlog.get_logger()

#: Valor de ``prompt_version`` en las respuestas del endpoint de sesión.
SESSION_PROMPT_VERSION = "session-v1"

router = APIRouter(prefix="/sessions", tags=["sessions"])


class CreateSessionResponse(BaseModel):
    """Identificador de una sesión recién creada."""

    session_id: str = Field(description="UUID v4 que identifica la sesión.")


class SessionStateResponse(BaseModel):
    """Estado actual de una sesión, para depuración y para el panel del cliente."""

    session_id: str
    turns: int = Field(description="Número de turnos que quedan en la ventana deslizante.")
    max_turns: int = Field(description="Tamaño de la ventana deslizante.")
    project_metadata: ProjectMetadata


def _require_session(session_id: str, store: SessionStore):
    """Devuelve la sesión con ``session_id`` o lanza HTTP 404.

    :param session_id: Identificador de la ruta.
    :param store: Almacén de sesiones en el que buscar.
    :returns: La :class:`~app.services.sessions.Session` correspondiente.
    :raises HTTPException: Con código 404 si la sesión no existe.
    """
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No se encontró la sesión {session_id!r}.")
    return session


@router.post("", status_code=201, response_model=CreateSessionResponse)
def create_session(store: SessionStore = Depends(get_session_store)) -> CreateSessionResponse:
    """Crea una sesión vacía y devuelve su identificador.

    El cliente guarda el identificador y lo envía en cada petición posterior, para
    que se reutilicen el historial de la conversación y los metadatos del proyecto.

    :param store: Almacén de sesiones, inyectado por FastAPI.
    :returns: El identificador de la nueva sesión.
    """
    session = store.create()
    log.info("session_created", session_id=session.session_id)
    return CreateSessionResponse(session_id=session.session_id)


@router.get("/{session_id}", response_model=SessionStateResponse)
def get_session(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
) -> SessionStateResponse:
    """Devuelve los metadatos del proyecto y el número de turnos de una sesión.

    :param session_id: Identificador devuelto por ``POST /sessions``.
    :param store: Almacén de sesiones, inyectado por FastAPI.
    :returns: El estado actual de la sesión.
    :raises HTTPException: Con código 404 si la sesión no existe.
    """
    session = _require_session(session_id, store)
    return SessionStateResponse(
        session_id=session.session_id,
        turns=session.history.turn_count,
        max_turns=session.history.max_turns,
        project_metadata=session.metadata,
    )


@router.post("/{session_id}/estimate", response_model=EstimationResponse)
def estimate_in_session(
    session_id: str,
    transcript: str = Form(..., min_length=1, max_length=80000, description="Transcripción de la reunión o notas del proyecto."),
    attachments: list[UploadFile] | None = File(default=None, description="Documentos opcionales .txt, .md o .pdf."),
    store: SessionStore = Depends(get_session_store),
    wrapper: LLMWrapper = Depends(get_llm_wrapper),
) -> EstimationResponse:
    """Estima el proyecto en el contexto de una sesión.

    El flujo es:

    1. Extraer el texto de cada adjunto y concatenarlo a la transcripción (camino B, ver el README).
    2. Renderizar el system prompt a partir de los :class:`ProjectMetadata` actuales.
    3. Llamar al LLM con el system prompt, el historial de la ventana y el mensaje nuevo.
    4. Añadir el turno al historial y actualizar los metadatos a partir del turno nuevo.

    :param session_id: Identificador devuelto por ``POST /sessions``.
    :param transcript: Transcripción de la reunión o notas escritas en el formulario.
    :param attachments: Documentos subidos de forma opcional.
    :param store: Almacén de sesiones, inyectado por FastAPI.
    :param wrapper: Wrapper compartido del LLM, inyectado por FastAPI.
    :returns: El texto de la estimación y la etiqueta de versión ``session-v1``.
    :raises HTTPException: 404 si la sesión no existe, 422 si un adjunto no está admitido
        o no se puede leer, y 500 si la llamada al LLM falla.
    """
    session = _require_session(session_id, store)

    parsed: list[tuple[str, str]] = []
    for upload in attachments or []:
        name = Path(upload.filename or "adjunto.txt").name
        try:
            parsed.append((name, extract_text(name, upload.file.read())))
        except AttachmentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    user_message = build_transcript_with_attachments(transcript, parsed)
    system_prompt = render_session_system_prompt(session.metadata)
    history = session.history.turns()

    try:
        result = wrapper.complete(
            system_prompt=system_prompt,
            user_message=user_message,
            history=history,
            max_tokens=ESTIMATION_MAX_TOKENS,
        )
    except Exception as exc:  # noqa: BLE001 — cualquier fallo del proveedor se traduce a 500
        log.error("session_estimation_failed", session_id=session_id, error=str(exc))
        raise HTTPException(status_code=500, detail=f"La llamada al LLM falló: {exc}") from exc

    text = result["estimation"]
    session.history.add_turn(user_message, text)
    session.metadata = update_metadata(session.metadata, user_message, text)
    log.info(
        "session_turn_completed",
        session_id=session_id,
        turns=session.history.turn_count,
        attachments=len(parsed),
    )
    return EstimationResponse(text=text, prompt_version=SESSION_PROMPT_VERSION)
