"""Extracción heurística de hechos para :class:`~app.services.sessions.ProjectMetadata`.

Tras cada respuesta del LLM, el router llama a :func:`update_metadata` con el
mensaje del usuario y la respuesta. La extracción usa solo expresiones regulares
y tratamiento de cadenas, sin una segunda llamada al LLM. El razonamiento está en
el README: es la vía barata, es determinista y se puede probar con muestras fijas,
y el formato de salida del system prompt es lo bastante estable para que los
encabezados y las viñetas sean señales fiables.

Reglas de fusión
----------------
* ``project_name`` es persistente: se conserva el primer nombre encontrado, para
  que el modelo no renombre el proyecto por accidente en un turno posterior.
* ``mentioned_technologies`` es la unión de todos los turnos, sin duplicados
  (sin distinguir mayúsculas).
* ``assumed_team_size`` y ``agreed_scope`` se reemplazan cuando la última
  respuesta los contiene, y se conservan en caso contrario.
"""

from __future__ import annotations

import re

from app.services.sessions import ProjectMetadata

#: Tecnologías reconocidas en la conversación, con su forma canónica.
TECHNOLOGY_KEYWORDS: tuple[str, ...] = (
    "Python",
    "FastAPI",
    "Django",
    "Flask",
    "Streamlit",
    "React",
    "React Native",
    "Vue",
    "Angular",
    "Next.js",
    "Node.js",
    "TypeScript",
    "JavaScript",
    "Java",
    "Spring",
    "Kotlin",
    "Swift",
    "Flutter",
    "Android",
    "iOS",
    "PostgreSQL",
    "MySQL",
    "MongoDB",
    "Redis",
    "Docker",
    "Kubernetes",
    "AWS",
    "Azure",
    "Stripe",
    "HubSpot",
    "Salesforce",
    "SAP",
    "Odoo",
    "OpenAI",
    "Anthropic",
)

#: Encabezados que describen una sección de la estimación y no el proyecto.
#: Nunca se toman como nombre del proyecto.
GENERIC_HEADINGS: frozenset[str] = frozenset(
    {
        "project summary",
        "task breakdown",
        "totals",
        "recommended team",
        "estimated duration",
        "risks and assumptions",
        "estimation",
        "resumen del proyecto",
        "desglose de tareas",
        "totales",
        "equipo recomendado",
        "duración estimada",
        "riesgos y supuestos",
        "estimación",
    }
)

_LABEL_RE = re.compile(
    r"^\s*(?:proyecto|project)\s*:\s*(?P<name>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_H2_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$", re.MULTILINE)
_BULLET_RE = re.compile(
    r"^\s*(?:[-*]|\d+\.)\s+(?:(?P<count>\d+)\s+)?\S",
    re.MULTILINE,
)

_TEAM_HEADING = r"team|equipo"
_SCOPE_HEADING = r"project summary|executive summary|resumen( del proyecto)?|resumen ejecutivo"

_MAX_SCOPE_CHARS = 300
_MAX_NAME_CHARS = 200


def _section(text: str, heading_pattern: str) -> str | None:
    """Devuelve el cuerpo del primer encabezado cuyo título coincide con ``heading_pattern``.

    El cuerpo va desde la línea siguiente al encabezado hasta el siguiente encabezado
    de cualquier nivel, o hasta el final del texto.

    :param text: Texto Markdown en el que buscar.
    :param heading_pattern: Expresión regular que se compara con los títulos, sin distinguir mayúsculas.
    :returns: El texto bruto del cuerpo, o ``None`` si ningún encabezado coincide.
    """
    for match in _HEADING_RE.finditer(text):
        if re.search(heading_pattern, match.group("title"), re.IGNORECASE):
            next_heading = _HEADING_RE.search(text, match.end())
            end = next_heading.start() if next_heading else len(text)
            return text[match.end() : end]
    return None


def extract_project_name(text: str) -> str | None:
    """Busca un nombre de proyecto, primero en una etiqueta explícita y después en un encabezado de nivel 2.

    Una etiqueta explícita como ``Proyecto: Gestor de inventario`` tiene prioridad.
    Si no existe, se usa el primer encabezado ``## `` que no sea un título genérico de sección.

    :param text: Transcripción del usuario o respuesta del modelo.
    :returns: El nombre, recortado a 200 caracteres, o ``None`` si no se encuentra nada adecuado.
    """
    label = _LABEL_RE.search(text)
    if label:
        return label.group("name").strip()[:_MAX_NAME_CHARS]
    for match in _H2_RE.finditer(text):
        title = match.group("title").strip()
        if title.lower() not in GENERIC_HEADINGS:
            return title[:_MAX_NAME_CHARS]
    return None


def extract_technologies(text: str) -> list[str]:
    """Lista las tecnologías conocidas que aparecen en ``text``.

    La comparación no distingue mayúsculas y respeta los límites de palabra, así que
    ``Java`` no coincide dentro de ``JavaScript``. El resultado sigue el orden de
    :data:`TECHNOLOGY_KEYWORDS`.

    :param text: Texto en el que buscar.
    :returns: Nombres canónicos de las tecnologías encontradas, sin duplicados.
    """
    found: list[str] = []
    for keyword in TECHNOLOGY_KEYWORDS:
        pattern = r"(?<![\w.])" + re.escape(keyword) + r"(?!\w)"
        if re.search(pattern, text, re.IGNORECASE):
            found.append(keyword)
    return found


def extract_team_size(text: str) -> int | None:
    """Cuenta el número de personas de la sección de equipo de una estimación.

    Cada viñeta de la sección cuenta como una persona. Una viñeta que empieza por
    un número, como ``- 2 Desarrolladores``, cuenta como esas personas.

    :param text: Respuesta del modelo que contiene una sección titulada «Team» o «Equipo».
    :returns: El total de personas, o ``None`` si no hay sección de equipo o está vacía.
    """
    section = _section(text, _TEAM_HEADING)
    if section is None:
        return None
    total = sum(int(match.group("count") or 1) for match in _BULLET_RE.finditer(section))
    return total or None


def extract_agreed_scope(text: str) -> str | None:
    """Toma el primer párrafo de la sección de resumen del proyecto.

    :param text: Respuesta del modelo que contiene una sección de resumen.
    :returns: El primer párrafo con los espacios colapsados, recortado a 300 caracteres,
        o ``None`` si no hay sección de resumen.
    """
    section = _section(text, _SCOPE_HEADING)
    if section is None:
        return None
    first_paragraph = re.split(r"\n\s*\n", section.strip(), maxsplit=1)[0]
    collapsed = " ".join(first_paragraph.split())
    return collapsed[:_MAX_SCOPE_CHARS] or None


def _merge_unique(existing: list[str], new: list[str]) -> list[str]:
    """Añade los elementos de ``new`` que no están ya en ``existing``, sin distinguir mayúsculas.

    :param existing: Elementos ya conocidos, en su orden.
    :param new: Elementos candidatos a añadir.
    :returns: Una lista nueva con la unión de ambos, en orden de primera aparición.
    """
    merged = list(existing)
    seen = {item.lower() for item in merged}
    for item in new:
        if item.lower() not in seen:
            merged.append(item)
            seen.add(item.lower())
    return merged


def update_metadata(
    current: ProjectMetadata,
    user_message: str,
    assistant_message: str,
) -> ProjectMetadata:
    """Devuelve los metadatos del proyecto tras un turno más de conversación.

    Las reglas de fusión están en el docstring del módulo. La función no modifica
    ``current``: devuelve un :class:`ProjectMetadata` nuevo.

    :param current: Metadatos antes de este turno.
    :param user_message: Mensaje del usuario de este turno, incluido el texto de los adjuntos.
    :param assistant_message: Respuesta del modelo de este turno.
    :returns: Los metadatos actualizados.
    """
    project_name = (
        current.project_name
        or extract_project_name(user_message)
        or extract_project_name(assistant_message)
    )
    technologies = _merge_unique(
        current.mentioned_technologies,
        extract_technologies(f"{user_message}\n{assistant_message}"),
    )
    team_size = extract_team_size(assistant_message) or current.assumed_team_size
    scope = extract_agreed_scope(assistant_message) or current.agreed_scope

    return ProjectMetadata(
        project_name=project_name,
        assumed_team_size=team_size,
        mentioned_technologies=technologies,
        agreed_scope=scope,
    )
