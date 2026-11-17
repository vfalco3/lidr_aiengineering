"""Generador de PDFs sintéticos de tamaño calibrado para el escenario de adjuntos.

El tamaño se calibra en bytes del archivo final, no en páginas: :func:`build_sized_pdf`
ajusta el número de líneas hasta quedarse dentro de un 2 % del objetivo. Cada PDF lleva
los marcadores de :data:`~evals.stress.scenarios.ATTACHMENT_MARKERS` en la primera y en
la última línea, para medir cuánto del adjunto llega a la respuesta.

El escritor es propio y multipágina porque el de ``tests/sample_data.py`` solo escribe
una página. Solo usa Helvetica y ASCII, así que cualquier analizador de PDF lo lee sin ambigüedad.
"""

from __future__ import annotations

from collections.abc import Sequence

from evals.stress.scenarios import ATTACHMENT_MARKERS

#: Líneas de texto por página, con fuente de 10 pt y 12 pt de interlineado.
LINES_PER_PAGE = 46

_FILLER_LINES: tuple[str, ...] = (
    "El sistema registra cada movimiento de stock con fecha, usuario y almacen.",
    "Las alertas de stock bajo se envian al responsable del almacen por correo.",
    "La exportacion genera un CSV con separador de punto y coma.",
    "Los datos de cada almacen quedan aislados de los demas inquilinos.",
)

_HEAD_MARKER_LINE = f"{ATTACHMENT_MARKERS[0]}: exportacion a CSV del inventario de existencias."
_TAIL_MARKER_LINE = f"{ATTACHMENT_MARKERS[1]}: alertas de caducidad por lote."

#: Estimación inicial de bytes por línea, usada solo como punto de partida de la calibración.
_BYTES_PER_LINE_ESTIMATE = 110

#: Tolerancia relativa aceptada respecto al tamaño objetivo.
_TOLERANCE = 0.02

_MAX_CALIBRATION_STEPS = 8


def _escape(text: str) -> str:
    """Escapa los caracteres que tienen significado dentro de una cadena PDF.

    :param text: Texto ASCII de una línea.
    :returns: El texto con ``\\``, ``(`` y ``)`` escapados.
    """
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def body_lines(count: int) -> list[str]:
    """Genera ``count`` líneas de texto con los marcadores en la primera y la última.

    :param count: Número total de líneas. Debe ser al menos 2 para que quepan los dos marcadores.
    :returns: Lista de líneas ASCII de longitud acotada.
    :raises ValueError: Si ``count`` es menor que 2.
    """
    if count < 2:
        raise ValueError("count debe ser al menos 2 para incluir los dos marcadores")
    lines = []
    for index in range(count):
        filler = _FILLER_LINES[index % len(_FILLER_LINES)]
        lines.append(f"{index + 1:05d} {filler}")
    lines[0] = _HEAD_MARKER_LINE
    lines[-1] = _TAIL_MARKER_LINE
    return lines


def _content_stream(lines: Sequence[str]) -> bytes:
    """Construye el flujo de contenido de una página con sus líneas en Helvetica.

    :param lines: Líneas de la página.
    :returns: El flujo de contenido en bytes, codificado en latín-1.
    """
    parts = ["BT", "/F1 10 Tf", "12 TL", "50 760 Td"]
    parts.extend(f"({_escape(line)}) '" for line in lines)
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def _render_pdf(lines: Sequence[str]) -> bytes:
    """Escribe un PDF multipágina con las líneas repartidas en páginas de :data:`LINES_PER_PAGE`.

    La tabla de referencias cruzadas se calcula con los desplazamientos reales.

    :param lines: Todas las líneas del documento, en orden.
    :returns: Los bytes brutos del PDF.
    """
    pages = [lines[start : start + LINES_PER_PAGE] for start in range(0, len(lines), LINES_PER_PAGE)]
    page_count = len(pages)
    font_number = 3 + 2 * page_count
    kids = " ".join(f"{3 + 2 * index} 0 R" for index in range(page_count))

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode(),
    ]
    for index, page in enumerate(pages):
        page_number = 3 + 2 * index
        content_number = page_number + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_number} 0 R "
            f"/Resources << /Font << /F1 {font_number} 0 R >> >> >>".encode()
        )
        stream = _content_stream(page)
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_position = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_position}\n%%EOF\n"
    ).encode()
    return bytes(out)


def build_sized_pdf(target_kb: int) -> bytes:
    """Genera un PDF cuyo tamaño final se acerca a ``target_kb`` KiB.

    Se parte de una estimación de bytes por línea y se corrige proporcionalmente
    hasta quedar dentro de :data:`_TOLERANCE` o agotar los pasos de calibración.
    Se devuelve el intento más cercano al objetivo.

    :param target_kb: Tamaño objetivo en KiB. Debe ser positivo; el caso 0 lo gestiona el llamador.
    :returns: Los bytes del PDF generado.
    :raises ValueError: Si ``target_kb`` no es positivo.
    """
    if target_kb <= 0:
        raise ValueError("target_kb debe ser positivo; el caso sin adjunto no genera PDF")
    target = target_kb * 1024
    count = max(2, target // _BYTES_PER_LINE_ESTIMATE)
    best: bytes | None = None
    for _ in range(_MAX_CALIBRATION_STEPS):
        candidate = _render_pdf(body_lines(count))
        if best is None or abs(len(candidate) - target) < abs(len(best) - target):
            best = candidate
        if abs(len(candidate) - target) <= target * _TOLERANCE:
            break
        count = max(2, round(count * target / len(candidate)))
    assert best is not None
    return best
