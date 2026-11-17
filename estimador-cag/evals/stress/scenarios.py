"""Perfiles de conversación multi-turno y escenario de adjuntos del harness de estrés.

Cada perfil fuerza un comportamiento distinto del sistema:

* ``growing``: el proyecto crece turno a turno; se mide si el nombre original sobrevive.
* ``pivot``: en el turno 5 cambia el frontend de React a Flutter; se mide si
  ``mentioned_technologies`` acumula ambas tecnologías.
* ``contradiction``: en el turno 3 el presupuesto es 30k€ y en el turno 8 pasa a 80k€;
  se mide cuál se conserva.

Cada perfil declara un fact-tracker: los :class:`Fact` que deben seguir presentes
en turnos posteriores. Los hechos con ``should_persist=False`` son hechos superados:
su presencia se cuenta como contaminación, no como acierto.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Perfiles disponibles, en el orden en que los ejecuta el runner.
PROFILE_NAMES: tuple[str, ...] = ("growing", "pivot", "contradiction")

#: Número de turnos que tiene cada perfil.
MAX_PROFILE_TURNS = 20

#: Nombre con el que el runner adjunta el PDF sintético.
ATTACHMENT_FILENAME = "requisitos.pdf"

#: Transcripción del escenario de adjuntos: una sola estimación inicial.
ATTACHMENT_TRANSCRIPT = (
    "Estima el proyecto descrito en el documento adjunto y ten en cuenta estas notas de la reunion."
)

#: Marcadores que el PDF sintético lleva al principio y al final. Su recall mide cuánto del adjunto llega a la respuesta.
ATTACHMENT_MARKERS: tuple[str, ...] = ("REQ-ADJ-INICIO", "REQ-ADJ-FIN")

_GROWING_REQUIREMENTS: tuple[str, ...] = (
    "Añade autenticación con inicio de sesión por correo y contraseña.",
    "Hazlo multi-tenant, con datos separados por almacén.",
    "Incluye un registro de auditoría de cada movimiento de stock.",
    "Añade exportación a CSV del listado de existencias.",
    "Define roles de operario y de responsable de almacén.",
    "Envía notificaciones por correo cuando el stock baje del mínimo.",
    "Importa altas masivas desde Excel con validación de filas.",
    "Lee códigos de barras desde el móvil durante la toma de datos.",
    "Planifica inventarios cíclicos por zonas del almacén.",
    "Controla la caducidad por lote con alertas previas.",
    "Integra el stock con el ERP mediante una API REST.",
    "Genera informes mensuales en PDF.",
    "Muestra un panel de indicadores para el responsable.",
    "Permite reservar material para pedidos concretos.",
    "Guarda el histórico de precios de compra.",
    "Haz copias de seguridad diarias cifradas.",
    "Ofrece un modo sin conexión para la toma de datos.",
    "Admite español e inglés en la interfaz.",
    "Limita el acceso a la API por dirección IP.",
)

_FILLER_SENTENCES: tuple[str, ...] = (
    "los usuarios ven el estado de cada elemento en una tabla filtrable.",
    "el responsable recibe un resumen semanal por correo.",
    "las acciones masivas piden confirmación antes de aplicar cambios.",
    "cada cambio queda registrado con fecha y usuario.",
)


@dataclass(frozen=True)
class Fact:
    """Hecho que el fact-tracker espera que el sistema recuerde.

    :ivar turn: Turno en el que se declara o se supera el hecho, contado desde 1.
    :ivar text: Texto que debe aparecer (o no, si está superado) en el snapshot.
    :ivar where: Campos del snapshot en los que se busca.
    :ivar should_persist: ``True`` si el hecho debe seguir presente; ``False`` si está superado.
    """

    turn: int
    text: str
    where: tuple[str, ...] = ("summary", "anchors", "metadata")
    should_persist: bool = True


@dataclass(frozen=True)
class Scenario:
    """Conversación completa de un perfil: transcripciones por turno y su fact-tracker.

    :ivar name: Nombre del perfil.
    :ivar transcripts: Mensaje del usuario en cada turno; la posición 0 es el turno 1.
    :ivar facts: Hechos del fact-tracker.
    """

    name: str
    transcripts: tuple[str, ...]
    facts: tuple[Fact, ...]

    def facts_due_at(self, turn_index: int) -> tuple[Fact, ...]:
        """Hechos que deben seguir presentes en ``turn_index``: declarados antes y no superados.

        :param turn_index: Turno 1-based del snapshot que se evalúa.
        :returns: Los hechos con ``turn < turn_index`` y ``should_persist=True``.
        """
        return tuple(fact for fact in self.facts if fact.should_persist and fact.turn < turn_index)

    def superseded_due_at(self, turn_index: int) -> tuple[Fact, ...]:
        """Hechos superados que ya no deberían aparecer en ``turn_index``.

        :param turn_index: Turno 1-based del snapshot que se evalúa.
        :returns: Los hechos con ``turn < turn_index`` y ``should_persist=False``.
        """
        return tuple(fact for fact in self.facts if not fact.should_persist and fact.turn < turn_index)


def _filler(turn_index: int, topic: str) -> str:
    """Genera una frase de relleno determinista que no contiene ningún hecho del fact-tracker.

    :param turn_index: Turno al que pertenece la frase.
    :param topic: Tema de la aplicación, para dar contexto.
    :returns: Una frase de requisito de relleno.
    """
    sentence = _FILLER_SENTENCES[turn_index % len(_FILLER_SENTENCES)]
    return f"Detalle {turn_index} sobre {topic}: {sentence}"


def _growing() -> Scenario:
    """Perfil que crece: un requisito nuevo por turno, sin cambiar el nombre del proyecto.

    :returns: El escenario de 20 turnos con el nombre original como hecho a conservar.
    """
    intro = (
        "Proyecto: Gestor de inventario para almacén. "
        "Queremos una web en Python con FastAPI y PostgreSQL para controlar el stock."
    )
    transcripts = (intro, *(f"Requisito nuevo: {req}" for req in _GROWING_REQUIREMENTS))
    facts = (
        Fact(1, "Gestor de inventario para almacén", where=("metadata",)),
        Fact(1, "PostgreSQL", where=("metadata",)),
    )
    return Scenario("growing", transcripts, facts)


def _pivot() -> Scenario:
    """Perfil que pivota: en el turno 5 el frontend pasa de React a Flutter.

    :returns: El escenario de 20 turnos con Flutter como hecho vigente y React como hecho superado.
    """
    head = (
        "Proyecto: App de pedidos para restaurantes. "
        "Backend en FastAPI con PostgreSQL y frontend en React para el personal de sala.",
        "Los pedidos tienen mesa, comensales y notas por plato.",
        "Necesitamos un listado de pedidos por hora.",
        "Queremos tickets que se impriman en la cocina.",
        "Cambio de planes: el frontend será en Flutter en lugar de React, para tablets Android.",
    )
    tail = tuple(_filler(index, "la app de pedidos") for index in range(6, MAX_PROFILE_TURNS + 1))
    facts = (
        Fact(1, "App de pedidos para restaurantes", where=("metadata",)),
        Fact(1, "FastAPI", where=("metadata",)),
        Fact(5, "Flutter", where=("metadata",)),
        Fact(5, "React", where=("metadata",), should_persist=False),
    )
    return Scenario("pivot", head + tail, facts)


def _contradiction() -> Scenario:
    """Perfil contradictorio: el presupuesto pasa de 30k€ a 80k€ en el turno 8.

    :returns: El escenario de 20 turnos con 80k€ como hecho vigente y 30k€ como superado.
    """
    head = {
        1: "Proyecto: Portal de reservas para clínicas. Web en Python con FastAPI para reservar citas.",
        2: "Necesitamos un calendario por consulta con bloqueo de huecos.",
        3: "El presupuesto disponible es de 30k€.",
        8: "Tras hablar con dirección, el presupuesto es de 80k€, no 30k€.",
    }
    transcripts = tuple(
        head[index] if index in head else _filler(index, "el portal de reservas")
        for index in range(1, MAX_PROFILE_TURNS + 1)
    )
    facts = (
        Fact(1, "Portal de reservas para clínicas", where=("metadata",)),
        Fact(8, "80k€"),
        Fact(8, "30k€", should_persist=False),
    )
    return Scenario("contradiction", transcripts, facts)


_BUILDERS = {"growing": _growing, "pivot": _pivot, "contradiction": _contradiction}


def build_profile(name: str) -> Scenario:
    """Construye uno de los perfiles de estrés por su nombre.

    :param name: Uno de los valores de :data:`PROFILE_NAMES`.
    :returns: El escenario completo de :data:`MAX_PROFILE_TURNS` turnos.
    :raises ValueError: Si el nombre no es un perfil conocido.
    """
    if name not in _BUILDERS:
        raise ValueError(f"perfil desconocido {name!r}; se esperaba uno de {PROFILE_NAMES}")
    return _BUILDERS[name]()
