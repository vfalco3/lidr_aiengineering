"""Métricas binarias del harness de estrés: presupuestos y deriva de memoria.

Por qué un módulo propio y no ``evals/metrics.py``
---------------------------------------------------
En esta copia del repositorio no existe ``evals/metrics.py`` ni el par
``MetricResult`` / ``run_all_metrics`` del framework de evals. Este módulo replica
ese mismo contrato (``name``, ``score``, ``passed``, ``details``), de modo que se
puede fusionar después sin reescribir nada.

Determinismo
------------
Ninguna métrica usa embeddings ni LLM-as-judge. :class:`MemoryDriftMetric` busca
el hecho como subcadena, sin distinguir mayúsculas, dentro de los campos del snapshot.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

#: Campos del snapshot de sesión en los que puede buscarse un hecho.
SNAPSHOT_FIELDS: tuple[str, ...] = ("summary", "anchors", "metadata")


@dataclass(frozen=True)
class MetricResult:
    """Resultado de una métrica sobre un sujeto: una observación o un snapshot.

    :ivar name: Nombre estable de la métrica, usado como cabecera de columna.
    :ivar score: 1.0 si la métrica se cumple, 0.0 si no.
    :ivar passed: ``True`` cuando ``score`` vale 1.0.
    :ivar details: Texto corto para depurar el resultado.
    """

    name: str
    score: float
    passed: bool
    details: str = ""


class Metric(Protocol):
    """Contrato de una métrica: evaluar un sujeto y devolver un :class:`MetricResult`."""

    def evaluate(self, subject: Any) -> MetricResult:
        """Evalúa el sujeto.

        :param subject: Observación de turno o snapshot de sesión, según la métrica.
        :returns: El resultado binario de la evaluación.
        """
        ...


def run_all_metrics(metrics: Iterable[Metric], subject: Any) -> list[MetricResult]:
    """Evalúa todas las métricas sobre el mismo sujeto, en el orden recibido.

    :param metrics: Métricas a aplicar.
    :param subject: Observación o snapshot común a todas.
    :returns: Un resultado por métrica, en el mismo orden.
    """
    return [metric.evaluate(subject) for metric in metrics]


def _require(observation: Mapping[str, Any], key: str) -> Any:
    """Devuelve ``observation[key]`` o falla con un mensaje claro si falta o es ``None``.

    :param observation: Diccionario de observación de un turno.
    :param key: Campo obligatorio.
    :returns: El valor del campo.
    :raises KeyError: Si el campo no existe o es ``None``.
    """
    if observation.get(key) is None:
        raise KeyError(f"La observación no contiene el campo obligatorio {key!r}.")
    return observation[key]


def _result(name: str, passed: bool, details: str) -> MetricResult:
    """Construye un :class:`MetricResult` binario a partir de un booleano.

    :param name: Nombre de la métrica.
    :param passed: Si la métrica se cumple.
    :param details: Texto de depuración.
    :returns: El resultado con ``score`` 1.0 o 0.0.
    """
    return MetricResult(name=name, score=1.0 if passed else 0.0, passed=passed, details=details)


class LatencyBudgetMetric:
    """1.0 si ``latency_ms`` es menor o igual que ``budget_ms``; 0.0 si no.

    :param budget_ms: Presupuesto de latencia en milisegundos. Debe ser positivo.
    :raises ValueError: Si ``budget_ms`` no es positivo.
    """

    name = "latency_budget"

    def __init__(self, budget_ms: int) -> None:
        if budget_ms <= 0:
            raise ValueError("budget_ms debe ser positivo")
        self.budget_ms = budget_ms

    def evaluate(self, observation: Mapping[str, Any]) -> MetricResult:
        """Compara la latencia del turno con el presupuesto.

        :param observation: Observación de turno con la clave ``latency_ms``.
        :returns: El resultado de la comparación.
        """
        latency = _require(observation, "latency_ms")
        return _result(self.name, latency <= self.budget_ms, f"latency_ms={latency} budget_ms={self.budget_ms}")


class CostBudgetMetric:
    """1.0 si ``cost_usd`` es menor o igual que ``budget_usd``; 0.0 si no.

    :param budget_usd: Presupuesto de coste por turno en dólares. No puede ser negativo.
    :raises ValueError: Si ``budget_usd`` es negativo.
    """

    name = "cost_budget"

    def __init__(self, budget_usd: float) -> None:
        if budget_usd < 0:
            raise ValueError("budget_usd no puede ser negativo")
        self.budget_usd = budget_usd

    def evaluate(self, observation: Mapping[str, Any]) -> MetricResult:
        """Compara el coste del turno con el presupuesto.

        :param observation: Observación de turno con la clave ``cost_usd``.
        :returns: El resultado de la comparación.
        """
        cost = _require(observation, "cost_usd")
        return _result(self.name, cost <= self.budget_usd, f"cost_usd={cost} budget_usd={self.budget_usd}")


def _flatten(value: Any) -> str:
    """Convierte un valor del snapshot en texto plano para buscar subcadenas.

    Los diccionarios y las listas se aplanan recursivamente y ``None`` se convierte
    en cadena vacía.

    :param value: Valor de un campo del snapshot.
    :returns: Texto con todos los valores separados por espacios.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return " ".join(_flatten(item) for item in value)
    return str(value)


class MemoryDriftMetric:
    """1.0 si el hecho aparece en alguno de los campos indicados del snapshot; 0.0 si no.

    La comparación es una subcadena sin distinguir mayúsculas. El llamador decide el
    turno: solo debe evaluar hechos declarados en un turno anterior al snapshot.

    :param fact: Texto del hecho que debe recordarse.
    :param where: Campos del snapshot en los que buscar. Por defecto, todos los de
        :data:`SNAPSHOT_FIELDS`. Se usa ``None`` en lugar de una lista mutable por defecto.
    :raises ValueError: Si ``fact`` está vacío, si ``where`` está vacío o si nombra un campo desconocido.
    """

    name = "memory_drift"

    def __init__(self, fact: str, where: Iterable[str] | None = None) -> None:
        if not fact or not fact.strip():
            raise ValueError("el hecho no puede estar vacío")
        fields = tuple(where) if where is not None else SNAPSHOT_FIELDS
        if not fields:
            raise ValueError("where no puede estar vacío")
        unknown = [field for field in fields if field not in SNAPSHOT_FIELDS]
        if unknown:
            raise ValueError(f"campos de snapshot desconocidos: {unknown}")
        self.fact = fact
        self.where = fields
        self.name = f"memory_drift:{fact}"

    def evaluate(self, session_snapshot: Mapping[str, Any]) -> MetricResult:
        """Busca el hecho en los campos configurados del snapshot.

        :param session_snapshot: Diccionario con las claves ``summary``, ``anchors`` y ``metadata``.
        :returns: 1.0 si el hecho aparece en algún campo buscado, 0.0 si no.
        """
        needle = self.fact.casefold()
        hits = [field for field in self.where if needle in _flatten(session_snapshot.get(field)).casefold()]
        return _result(self.name, bool(hits), f"fact={self.fact!r} found_in={hits or 'none'}")
