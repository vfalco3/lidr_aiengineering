"""Extracción de texto de los documentos de apoyo adjuntos a una estimación.

El servicio usa el camino **B** descrito en el README: los adjuntos se convierten
a texto plano dentro del servicio y se concatenan a la transcripción con un
separador claro. El modelo recibe así un único mensaje de usuario con las notas
de la reunión seguidas de cada documento, por ejemplo::

    <transcripción>

    --- attachment: requisitos.pdf ---
    <texto extraído del PDF>

Solo se aceptan formatos de texto: ``.txt``, ``.md`` y ``.pdf``. Los archivos más
grandes que :data:`MAX_ATTACHMENT_BYTES` se rechazan antes de analizarlos.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from pathlib import Path

from pypdf import PdfReader

#: Extensiones de archivo admitidas como adjuntos.
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".txt", ".md", ".pdf")

#: Tamaño máximo admitido por adjunto, en bytes (5 MiB).
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024

#: Plantilla de la línea separadora que precede al texto de cada adjunto.
ATTACHMENT_SEPARATOR = "--- attachment: {name} ---"


class AttachmentError(ValueError):
    """Se lanza cuando un adjunto tiene un tipo no admitido, es demasiado grande o no se puede leer."""


def extract_text(filename: str, data: bytes) -> str:
    """Convierte los bytes de un adjunto en texto plano.

    :param filename: Nombre original del archivo. Solo se usa su extensión para elegir el analizador.
    :param data: Contenido bruto del archivo subido.
    :returns: El texto extraído. Las páginas de un PDF se unen con un salto de línea y se omiten las vacías.
    :raises AttachmentError: Si la extensión no está admitida, si el archivo supera
        :data:`MAX_ATTACHMENT_BYTES` o si no se puede analizar el PDF.
    """
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise AttachmentError(
            f"Tipo de adjunto no admitido para {Path(filename).name!r}; "
            f"se esperaba uno de: {', '.join(SUPPORTED_EXTENSIONS)}."
        )
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentError(
            f"El adjunto {Path(filename).name!r} supera los {MAX_ATTACHMENT_BYTES} bytes permitidos."
        )
    if extension == ".pdf":
        return _extract_pdf_text(filename, data)
    return data.decode("utf-8", errors="replace")


def _extract_pdf_text(filename: str, data: bytes) -> str:
    """Lee todas las páginas de un PDF y une los textos de las páginas no vacías.

    :param filename: Nombre del archivo, usado solo en los mensajes de error.
    :param data: Bytes brutos del PDF.
    :returns: El texto concatenado de todas las páginas.
    :raises AttachmentError: Si pypdf no puede abrir o analizar el documento.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:  # noqa: BLE001 — cualquier fallo del analizador es un error del cliente aquí
        raise AttachmentError(f"No se pudo leer el PDF {Path(filename).name!r}: {exc}") from exc
    return "\n".join(page for page in pages if page)


def build_transcript_with_attachments(
    transcript: str,
    attachments: Sequence[tuple[str, str]],
) -> str:
    """Concatena la transcripción y los textos extraídos de los adjuntos.

    Cada adjunto va precedido de una línea separadora con su nombre, para que el
    modelo pueda referirse a un documento por su nombre.

    :param transcript: Transcripción de la reunión o notas del proyecto escritas por el usuario.
    :param attachments: Pares ``(nombre_archivo, texto_extraído)``, en el orden de subida.
    :returns: Una única cadena: la transcripción seguida de un bloque separador-y-texto por adjunto.
    """
    parts = [transcript.strip()]
    for name, text in attachments:
        parts.append(f"{ATTACHMENT_SEPARATOR.format(name=name)}\n{text.strip()}")
    return "\n\n".join(parts)
