"""Datos de prueba sintéticos para los tests de sesiones.

Todo es inventado: el proyecto, las personas y los requisitos. El generador de PDF
escribe un PDF válido de una página, para que el camino de los adjuntos se pruebe
con un analizador de PDF real sin tener que versionar un binario de prueba.
"""

from __future__ import annotations

SAMPLE_PROJECT_NAME = "Gestor de inventario para almacén"

#: Primera transcripción de una sesión: nombra el proyecto y dos tecnologías.
TRANSCRIPT_FIRST_TURN = (
    f"Proyecto: {SAMPLE_PROJECT_NAME}\n"
    "Queremos una web en Python con FastAPI y PostgreSQL para controlar el stock, "
    "con alertas de stock bajo y un panel en React para el responsable."
)

#: Mensaje de seguimiento que añade alcance sin volver a describir el proyecto.
TRANSCRIPT_FOLLOW_UP = "Añade un módulo de importación desde Excel con validación de filas."

#: Transcripción corta usada para comparar estimaciones con y sin adjunto.
TRANSCRIPT_SHORT = (
    "Necesitamos una aplicación interna para registrar entradas y salidas de material "
    "en un almacén con un listado de existencias."
)

#: Respuesta del modelo que sigue el formato de salida de la sesión.
SAMPLE_ANSWER = """## Gestor de inventario para almacén

### Project summary

Internal web platform that tracks stock movements for one warehouse, with low-stock alerts and CSV import. Out of scope: mobile apps.

### Task breakdown

| Task | Hours | Cost (EUR) |
|------|------:|------------|
| Backend API and stock model | 40 | 2,500 |
| Frontend inventory views | 24 | 1,500 |

### Totals

- Total hours: 64
- Total cost: 4,000 EUR

### Recommended team

- 2 Developers (1 backend, 1 frontend)
- 1 QA engineer

### Estimated duration

4 weeks
"""


def make_answer(total_hours: int) -> str:
    """Construye una respuesta mínima del modelo cuya línea ``Total hours`` contiene ``total_hours``.

    :param total_hours: Horas que se escriben en la sección de totales.
    :returns: Una estimación corta en Markdown.
    """
    return (
        "## Gestor de inventario para almacén\n\n"
        "### Totals\n"
        f"- Total hours: {total_hours}\n"
        f"- Total cost: {total_hours * 62.5:.0f} EUR\n"
    )


def make_text_pdf(lines: list[str]) -> bytes:
    """Construye un PDF mínimo y válido de una página cuyo texto son ``lines``.

    La tabla de referencias cruzadas se calcula con los desplazamientos reales, así
    que cualquier analizador de PDF lee el documento sin repararlo.

    :param lines: Líneas de texto, escritas una debajo de otra en Helvetica de 12 pt.
    :returns: Los bytes brutos del archivo PDF.
    """
    content = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            content.append("0 -16 Td")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content.append(f"({escaped}) Tj")
    content.append("ET")
    stream = "\n".join(content).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

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
