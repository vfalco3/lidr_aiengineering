"""Tests unitarios del estado de sesión, del extractor de metadatos y del manejo de adjuntos.

Estos tests no levantan FastAPI ni llaman a un LLM. Usan los datos sintéticos de
:mod:`tests.sample_data`.
"""

from __future__ import annotations

import uuid

import pytest

from app.prompts.loader import render_session_system_prompt
from app.services.attachments import (
    MAX_ATTACHMENT_BYTES,
    AttachmentError,
    build_transcript_with_attachments,
    extract_text,
)
from app.services.metadata_extractor import (
    extract_agreed_scope,
    extract_project_name,
    extract_team_size,
    extract_technologies,
    update_metadata,
)
from app.services.sessions import ConversationHistory, ProjectMetadata, SessionStore
from tests.sample_data import (
    SAMPLE_ANSWER,
    SAMPLE_PROJECT_NAME,
    TRANSCRIPT_FIRST_TURN,
    make_text_pdf,
)

# ---------------------------------------------------------------------------
# ConversationHistory: ventana deslizante
# ---------------------------------------------------------------------------


def _fill(history: ConversationHistory, turns: int) -> None:
    """Añade ``turns`` pares usuario/asistente numerados al historial."""
    for number in range(1, turns + 1):
        history.add_turn(f"user {number}", f"assistant {number}")


def test_window_keeps_only_the_most_recent_turns() -> None:
    """Con memoria de seis turnos, ocho turnos dejan los turnos 3 a 8, del más antiguo al más reciente."""
    history = ConversationHistory(max_turns=6)
    _fill(history, 8)

    assert history.turn_count == 6
    contents = [message["content"] for message in history.turns()]
    assert contents[0] == "user 3"
    assert contents[-1] == "assistant 8"


def test_window_never_splits_a_pair_and_always_starts_with_a_user_message() -> None:
    """El recorte elimina turnos completos, así que el primer mensaje guardado siempre es del usuario."""
    history = ConversationHistory(max_turns=2)
    for number in range(1, 6):
        history.add_turn(f"user {number}", f"assistant {number}")
        turns = history.turns()
        assert len(turns) % 2 == 0
        assert turns[0]["role"] == "user"


def test_window_size_is_respected_at_every_step() -> None:
    """El número de turnos guardados nunca supera ``max_turns``, en ningún momento de la conversación."""
    history = ConversationHistory(max_turns=3)
    for number in range(1, 20):
        history.add_turn(f"user {number}", f"assistant {number}")
        assert history.turn_count <= 3


def test_to_messages_list_puts_system_first_and_new_user_message_last() -> None:
    """El array de mensajes es ``[system, *historial, usuario]``; el system prompt no se guarda en el historial."""
    history = ConversationHistory(max_turns=6)
    _fill(history, 2)

    messages = history.to_messages_list(system_prompt="SYSTEM", user_message="NEW")

    assert messages[0] == {"role": "system", "content": "SYSTEM"}
    assert messages[-1] == {"role": "user", "content": "NEW"}
    assert len(messages) == 2 + 4
    assert all(message["role"] != "system" for message in history.turns())


def test_history_rejects_a_window_smaller_than_one() -> None:
    """Una ventana de cero turnos no tiene sentido y se rechaza al crear el objeto."""
    with pytest.raises(ValueError):
        ConversationHistory(max_turns=0)


# ---------------------------------------------------------------------------
# ProjectMetadata y SessionStore
# ---------------------------------------------------------------------------


def test_new_metadata_is_empty() -> None:
    """Un :class:`ProjectMetadata` recién creado indica que todavía no se conoce nada."""
    assert ProjectMetadata().is_empty()


def test_metadata_with_one_fact_is_not_empty() -> None:
    """Basta un solo hecho extraído para que los metadatos dejen de considerarse vacíos."""
    assert not ProjectMetadata(project_name="Demo").is_empty()


def test_store_creates_sessions_with_uuid4_identifiers() -> None:
    """Cada sesión recibe un UUID v4 nuevo y se puede recuperar por él."""
    store = SessionStore(max_turns=4)

    first = store.create()
    second = store.create()

    assert uuid.UUID(first.session_id).version == 4
    assert first.session_id != second.session_id
    assert store.get(first.session_id) is first
    assert store.get("no-existe") is None
    assert len(store) == 2
    assert first.history.max_turns == 4


# ---------------------------------------------------------------------------
# Extractor de metadatos
# ---------------------------------------------------------------------------


def test_project_name_comes_from_the_explicit_label() -> None:
    """La línea ``Proyecto:`` de la transcripción es la fuente más fiable del nombre."""
    assert extract_project_name(TRANSCRIPT_FIRST_TURN) == SAMPLE_PROJECT_NAME


def test_project_name_skips_generic_section_headings() -> None:
    """Encabezados como «Totals» describen la estimación, no el proyecto, y se ignoran."""
    text = "## Totals\n- Total hours: 10\n\n## Real Project Name\n"
    assert extract_project_name(text) == "Real Project Name"


def test_technologies_respect_word_boundaries_and_canonical_names() -> None:
    """``Java`` no debe coincidir dentro de ``JavaScript``, y los resultados usan la forma canónica."""
    found = extract_technologies("We use javascript for the widget and PostgreSQL in the back.")

    assert "JavaScript" in found
    assert "PostgreSQL" in found
    assert "Java" not in found


def test_team_size_counts_bullets_and_leading_numbers() -> None:
    """``- 2 Developers`` cuenta como dos personas y ``- 1 QA engineer`` como una: tres en total."""
    assert extract_team_size(SAMPLE_ANSWER) == 3


def test_team_size_is_none_without_a_team_section() -> None:
    """Una respuesta sin sección de equipo no da un número de personas inventado."""
    assert extract_team_size("## Only totals\n- Total hours: 5\n") is None


def test_agreed_scope_is_the_first_paragraph_of_the_summary() -> None:
    """El alcance es el primer párrafo del resumen, con los espacios colapsados."""
    scope = extract_agreed_scope(SAMPLE_ANSWER)

    assert scope is not None
    assert scope.startswith("Internal web platform that tracks stock movements")
    assert "Out of scope: mobile apps." in scope


def test_update_keeps_the_first_project_name_and_merges_technologies() -> None:
    """El nombre es persistente, y las tecnologías se acumulan entre turnos sin duplicados."""
    first = update_metadata(
        ProjectMetadata(),
        user_message=TRANSCRIPT_FIRST_TURN,
        assistant_message=SAMPLE_ANSWER,
    )
    second = update_metadata(
        first,
        user_message="Ahora con Stripe. Usamos python otra vez.",
        assistant_message="## Otro nombre\n\n### Recommended team\n- 4 Developers\n",
    )

    assert first.project_name == SAMPLE_PROJECT_NAME
    assert second.project_name == SAMPLE_PROJECT_NAME
    assert {"Python", "FastAPI", "PostgreSQL", "React", "Stripe"} <= set(second.mentioned_technologies)
    assert len(second.mentioned_technologies) == len({t.lower() for t in second.mentioned_technologies})
    assert second.assumed_team_size == 4


def test_update_does_not_modify_the_previous_metadata() -> None:
    """La función devuelve un objeto nuevo; los metadatos recibidos no cambian."""
    before = ProjectMetadata(project_name="Kept")
    update_metadata(before, user_message="Stripe", assistant_message="## Other\n")

    assert before.project_name == "Kept"
    assert before.mentioned_technologies == []


# ---------------------------------------------------------------------------
# Renderizado del system prompt de sesión
# ---------------------------------------------------------------------------


def test_system_prompt_has_no_metadata_block_on_the_first_call() -> None:
    """Una sesión vacía renderiza el prompt sin ningún bloque ``<project_metadata>``."""
    assert "<project_metadata>" not in render_session_system_prompt(ProjectMetadata())
    assert "<project_metadata>" not in render_session_system_prompt(None)


def test_system_prompt_injects_known_facts() -> None:
    """Los hechos conocidos aparecen dentro del bloque ``<project_metadata>``."""
    metadata = ProjectMetadata(
        project_name=SAMPLE_PROJECT_NAME,
        assumed_team_size=3,
        mentioned_technologies=["Python", "FastAPI"],
        agreed_scope="Stock tracking for one warehouse.",
    )

    prompt = render_session_system_prompt(metadata)

    assert "<project_metadata>" in prompt
    assert f"- Project name: {SAMPLE_PROJECT_NAME}" in prompt
    assert "- Assumed team size: 3 people" in prompt
    assert "- Mentioned technologies: Python, FastAPI" in prompt
    assert "- Agreed scope: Stock tracking for one warehouse." in prompt


def test_system_prompt_omits_fields_that_are_unknown() -> None:
    """Solo se escriben los hechos conocidos; los desconocidos no dejan viñetas vacías."""
    prompt = render_session_system_prompt(ProjectMetadata(project_name="Solo"))

    assert "- Project name: Solo" in prompt
    assert "Assumed team size" not in prompt
    assert "Mentioned technologies" not in prompt


# ---------------------------------------------------------------------------
# Adjuntos
# ---------------------------------------------------------------------------


def test_text_attachment_is_decoded_as_utf8() -> None:
    """Un archivo ``.txt`` conserva sus acentos y sus saltos de línea."""
    text = extract_text("notas.txt", "Requisito: validación de stock\nSegunda línea".encode("utf-8"))

    assert text == "Requisito: validación de stock\nSegunda línea"


def test_pdf_attachment_text_is_extracted() -> None:
    """Un PDF real de una página devuelve su texto, que contiene el requisito importante."""
    pdf = make_text_pdf(["Requisitos del cliente", "Integración con SAP para facturación"])

    text = extract_text("requisitos.pdf", pdf)

    assert "Requisitos del cliente" in text
    assert "Integración con SAP para facturación" in text


def test_unsupported_extension_is_rejected() -> None:
    """Solo se aceptan ``.txt``, ``.md`` y ``.pdf``."""
    with pytest.raises(AttachmentError, match="Tipo de adjunto no admitido"):
        extract_text("plano.dwg", b"binary")


def test_oversized_attachment_is_rejected_before_parsing() -> None:
    """Un archivo por encima del límite se rechaza sin llegar a leerse."""
    with pytest.raises(AttachmentError, match="supera los"):
        extract_text("grande.txt", b"x" * (MAX_ATTACHMENT_BYTES + 1))


def test_corrupt_pdf_is_reported_as_attachment_error() -> None:
    """Un archivo ``.pdf`` que no es un PDF produce un error de cliente, no un fallo."""
    with pytest.raises(AttachmentError, match="No se pudo leer el PDF"):
        extract_text("roto.pdf", b"this is not a pdf")


def test_attachment_names_are_stripped_of_directories() -> None:
    """La ruta que envía el cliente se reduce a su nombre de archivo antes de usarse."""
    text = extract_text("../../etc/notas.txt", b"contenido")

    assert text == "contenido"


def test_transcript_and_attachments_are_joined_with_a_clear_separator() -> None:
    """Cada adjunto empieza con la línea ``--- attachment: <nombre> ---``."""
    combined = build_transcript_with_attachments(
        "Reunión con el cliente.",
        [("requisitos.pdf", "Integración con SAP")],
    )

    assert combined.startswith("Reunión con el cliente.")
    assert "--- attachment: requisitos.pdf ---\nIntegración con SAP" in combined


def test_transcript_without_attachments_is_returned_unchanged_apart_from_whitespace() -> None:
    """Sin adjuntos el mensaje es la propia transcripción."""
    assert build_transcript_with_attachments("  Solo texto.  ", []) == "Solo texto."
