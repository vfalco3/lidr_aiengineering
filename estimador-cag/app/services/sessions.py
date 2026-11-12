"""Estado de sesión en memoria para estimaciones de varios turnos.

Una sesión guarda dos piezas de estado independientes, para que el modelo
nunca tenga que adivinar cuál importa:

* :class:`ConversationHistory`: los turnos recientes usuario/asistente, acotados
  por una ventana deslizante de ``max_turns`` pares. Responde a «qué se dijo antes».
* :class:`ProjectMetadata`: un conjunto de hechos estructurados sobre el proyecto
  (nombre, tamaño de equipo, tecnologías, alcance acordado). Responde a «qué se
  sabe ya de este proyecto». Se inyecta en el system prompt en cada llamada.

Ambas viven dentro de :class:`Session`. :class:`SessionStore` indexa las sesiones
por ``session_id`` en un diccionario que pertenece al proceso.

Por qué se acepta el almacenamiento volátil en esta fase
---------------------------------------------------------
El objetivo de esta etapa es aprender la *forma* del estado conversacional
(ventana, system prompt invariante, inyección de metadatos), no la durabilidad.
Guardar el estado en un diccionario simple evita aprovisionar una base de datos
y un salto de red que depurar. El coste es que cada sesión se pierde al reiniciar
el proceso y que varios workers no comparten sesiones. Ambos límites son
aceptables para un único proceso uvicorn local, y serían lo primero que cambiar
si el servicio necesitara más de una réplica.

El almacén usa un :class:`threading.Lock` porque FastAPI ejecuta los endpoints
síncronos en un pool de hilos.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

#: Número por defecto de pares usuario+asistente que se conservan en la ventana.
DEFAULT_MAX_TURNS = 6


class ProjectMetadata(BaseModel):
    """Hechos conocidos sobre el proyecto que se estima.

    Todos los campos son opcionales, así que una sesión nueva empieza vacía. El
    extractor de :mod:`app.services.metadata_extractor` rellena los campos tras
    cada respuesta del LLM.

    :ivar project_name: Nombre corto del proyecto, si se ha indicado o propuesto.
    :ivar assumed_team_size: Número de personas que asume la última estimación.
    :ivar mentioned_technologies: Tecnologías citadas en la conversación, sin duplicados.
    :ivar agreed_scope: Resumen libre del alcance, tomado de la última estimación.
    """

    project_name: str | None = Field(default=None, max_length=200)
    assumed_team_size: int | None = Field(default=None, ge=1)
    mentioned_technologies: list[str] = Field(default_factory=list)
    agreed_scope: str | None = Field(default=None, max_length=1000)

    def is_empty(self) -> bool:
        """Indica si todavía no se ha extraído ningún hecho.

        :returns: ``True`` cuando todos los campos tienen su valor por defecto.
        """
        return (
            self.project_name is None
            and self.assumed_team_size is None
            and not self.mentioned_technologies
            and self.agreed_scope is None
        )


class ConversationHistory:
    """Ventana deslizante sobre los turnos usuario/asistente de una sesión.

    El system prompt no se guarda aquí. Se regenera en cada llamada a partir de
    :class:`ProjectMetadata` actual, de modo que actúa como invariante: siempre
    está presente y nunca se recorta.

    Un turno es un mensaje de usuario más un mensaje del asistente. Cuando la
    ventana está llena se elimina el turno más antiguo completo, así que la lista
    nunca empieza por un mensaje del asistente ni separa un par.

    :param max_turns: Número máximo de pares usuario+asistente que se conservan. Debe ser al menos 1.
    :raises ValueError: Si ``max_turns`` es menor que 1.
    """

    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS) -> None:
        if max_turns < 1:
            raise ValueError("max_turns debe ser al menos 1")
        self._max_turns = max_turns
        self._messages: list[dict[str, str]] = []

    @property
    def max_turns(self) -> int:
        """Número máximo de turnos que caben en la ventana."""
        return self._max_turns

    @property
    def turn_count(self) -> int:
        """Número de turnos guardados en este momento (nunca mayor que :attr:`max_turns`)."""
        return len(self._messages) // 2

    def add_turn(self, user_message: str, assistant_message: str) -> None:
        """Añade un par usuario/asistente y descarta los pares más antiguos si la ventana se desborda.

        :param user_message: Contenido del mensaje del usuario, incluido el texto de los adjuntos.
        :param assistant_message: Contenido de la respuesta del modelo.
        """
        self._messages.append({"role": "user", "content": user_message})
        self._messages.append({"role": "assistant", "content": assistant_message})
        self._trim()

    def turns(self) -> list[dict[str, str]]:
        """Devuelve una copia de los mensajes guardados, del más antiguo al más reciente, sin el system prompt.

        :returns: Una lista nueva de diccionarios ``{"role", "content"}``.
        """
        return [dict(message) for message in self._messages]

    def to_messages_list(self, system_prompt: str, user_message: str) -> list[dict[str, str]]:
        """Construye el array ``messages`` que se envía al LLM en el siguiente turno.

        El array es ``[system, *historial, usuario]``. El system prompt lo proporciona
        quien llama, renderizado a partir de los metadatos actuales del proyecto.

        :param system_prompt: System prompt renderizado con los metadatos actuales.
        :param user_message: Mensaje nuevo del usuario para este turno.
        :returns: Los mensajes en el orden que espera la API de chat completions.
        """
        return [
            {"role": "system", "content": system_prompt},
            *self.turns(),
            {"role": "user", "content": user_message},
        ]

    def _trim(self) -> None:
        """Elimina los mensajes más antiguos hasta que queden como mucho ``max_turns`` pares."""
        excess = len(self._messages) - 2 * self._max_turns
        if excess > 0:
            del self._messages[:excess]


@dataclass
class Session:
    """Estado de una conversación: su historial y los hechos del proyecto conocidos hasta ahora.

    :ivar session_id: Identificador devuelto por ``POST /sessions``.
    :ivar history: Ventana deslizante de turnos recientes.
    :ivar metadata: Hechos extraídos de la conversación hasta el momento.
    """

    session_id: str
    history: ConversationHistory
    metadata: ProjectMetadata = field(default_factory=ProjectMetadata)


class SessionStore:
    """Diccionario de sesiones, seguro para hilos, indexado por ``session_id``.

    :param max_turns: Tamaño de la ventana deslizante que recibe el historial de cada sesión nueva.
    """

    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS) -> None:
        self._max_turns = max_turns
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> Session:
        """Crea una sesión vacía con un identificador UUID v4 aleatorio.

        :returns: La :class:`Session` recién creada.
        """
        session = Session(
            session_id=str(uuid.uuid4()),
            history=ConversationHistory(self._max_turns),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        """Busca una sesión por su identificador.

        :param session_id: Identificador devuelto antes por :meth:`create`.
        :returns: La sesión, o ``None`` si no existe en este proceso.
        """
        with self._lock:
            return self._sessions.get(session_id)

    def __len__(self) -> int:
        """Devuelve el número de sesiones que guarda el proceso."""
        with self._lock:
            return len(self._sessions)
