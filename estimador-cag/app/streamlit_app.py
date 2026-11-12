"""Cliente Streamlit para las sesiones de estimación de varios turnos.

El cliente es un cliente HTTP del servicio FastAPI:

* Al cargar por primera vez llama a ``POST /sessions`` y guarda el ``session_id``
  en ``st.session_state``.
* Cada estimación es una petición ``multipart/form-data`` a
  ``POST /sessions/{session_id}/estimate`` con la transcripción y los adjuntos opcionales.
* El panel de la barra lateral muestra el ``project_metadata`` que devuelve
  ``GET /sessions/{session_id}``, de modo que se ve la separación entre metadatos
  (lo que se sabe) e historial (lo que se dijo) mientras avanza la conversación.
* «Nueva conversación» crea una sesión nueva y limpia el chat local.

La URL base se lee de ``ESTIMATOR_API_BASE_URL`` (cargada desde ``.env``).
"""

from __future__ import annotations

import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("ESTIMATOR_API_BASE_URL", "http://localhost:8000").rstrip("/")
SESSIONS_URL = f"{API_BASE_URL}/sessions"
ACCEPTED_TYPES = ["txt", "md", "pdf"]
REQUEST_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

st.set_page_config(page_title="Software Estimator", page_icon="📊", layout="wide")
st.title("Software Estimator")
st.caption(
    "Describe the project or paste the meeting transcript, optionally attach documents, "
    "and send. Each message is answered in the context of the same session."
)


def create_session() -> str:
    """Crea una sesión en el servidor y devuelve su identificador.

    :returns: El ``session_id`` que devuelve ``POST /sessions``.
    :raises httpx.HTTPError: Si no se puede contactar con el servicio o rechaza la petición.
    """
    response = httpx.post(SESSIONS_URL, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()["session_id"]


def fetch_session_state(session_id: str) -> dict | None:
    """Lee los metadatos y el número de turnos de una sesión.

    :param session_id: Identificador de la sesión a leer.
    :returns: El cuerpo JSON de ``GET /sessions/{session_id}``, o ``None`` si la llamada falla.
    """
    try:
        response = httpx.get(f"{SESSIONS_URL}/{session_id}", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return response.json()


def send_estimation(session_id: str, transcript: str, uploads: list) -> str:
    """Envía la transcripción y los adjuntos al endpoint de la sesión.

    La petición es siempre ``multipart/form-data``. La transcripción se envía como
    campo de formulario, y cada archivo subido como una parte ``attachments``.

    :param session_id: Identificador de la sesión a continuar.
    :param transcript: Texto escrito en el formulario.
    :param uploads: Archivos devueltos por ``st.file_uploader``.
    :returns: El texto de la estimación de la respuesta.
    :raises httpx.HTTPStatusError: Si el servicio responde con un código de error.
    :raises httpx.HTTPError: Si no se puede contactar con el servicio.
    """
    fields: list[tuple[str, object]] = [("transcript", (None, transcript))]
    for upload in uploads:
        content_type = upload.type or "application/octet-stream"
        fields.append(("attachments", (upload.name, upload.getvalue(), content_type)))

    response = httpx.post(
        f"{SESSIONS_URL}/{session_id}/estimate",
        files=fields,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["text"]


def start_new_conversation() -> None:
    """Crea una sesión nueva y limpia el historial del chat local."""
    st.session_state.session_id = create_session()
    st.session_state.messages = []


if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    try:
        start_new_conversation()
    except httpx.HTTPError as exc:
        st.error(f"Could not create a session at `{SESSIONS_URL}`: {exc}")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

with st.form("estimate_form", clear_on_submit=True):
    transcript = st.text_area(
        "Transcript or project notes",
        height=180,
        placeholder="Paste the meeting transcript or describe the project...",
    )
    uploads = st.file_uploader(
        "Supporting documents (optional)",
        type=ACCEPTED_TYPES,
        accept_multiple_files=True,
    )
    submitted = st.form_submit_button("Estimate")

if submitted and "session_id" in st.session_state:
    if not transcript.strip():
        st.warning("Write a transcript or project notes before estimating.")
    else:
        attachment_names = [upload.name for upload in uploads]
        user_label = transcript
        if attachment_names:
            user_label += "\n\n_Attachments: " + ", ".join(attachment_names) + "_"
        st.session_state.messages.append({"role": "user", "content": user_label})
        with st.chat_message("user"):
            st.markdown(user_label)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Estimating..."):
                    answer = send_estimation(st.session_state.session_id, transcript, uploads)
                st.markdown(answer)
            except httpx.HTTPStatusError as exc:
                answer = f"The service rejected the request ({exc.response.status_code}): {exc.response.text}"
                st.error(answer)
            except httpx.HTTPError as exc:
                answer = f"Could not reach the estimator at `{SESSIONS_URL}`: {exc}"
                st.error(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})


with st.sidebar:
    st.header("Session")
    if "session_id" in st.session_state:
        st.code(st.session_state.session_id, language="text")
        state = fetch_session_state(st.session_state.session_id)
        if state is None:
            st.warning("Session state is not available.")
        else:
            st.caption(f"Turns kept: {state['turns']} of {state['max_turns']}")
            with st.expander("project_metadata", expanded=True):
                st.json(state["project_metadata"])
    if st.button("Nueva conversación"):
        try:
            start_new_conversation()
        except httpx.HTTPError as exc:
            st.error(f"Could not create a session: {exc}")
        st.rerun()
    st.markdown("---")
    st.markdown(f"**API:** `{API_BASE_URL}`")
