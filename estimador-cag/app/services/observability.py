"""Observación unificada por turno de una estimación de sesión.

Cada llamada al endpoint de sesión deja un único evento ``turn_observed`` con todo
lo necesario para construir una fila de CSV. Este módulo solo arma el diccionario:
no llama al LLM ni escribe en disco, así que se prueba con datos fijos.

Los campos ``anchors_count``, ``summary_chars`` y ``last_resolved_tier`` los fija
quien llama. En esta base de código no existen anclas, summarizer ni tiers, de modo
que el endpoint los envía como 0 o ``None`` en lugar de inventar un valor.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_turn_observation(
    *,
    session_id: str,
    turn_index: int,
    enriched_transcript_chars: int,
    attachments_total_chars: int,
    messages_in_window: int,
    anchors_count: int,
    summary_chars: int,
    result: Mapping[str, Any],
    latency_ms: int,
    last_resolved_tier: str | None = None,
) -> dict[str, Any]:
    """Construye el diccionario del evento ``turn_observed`` de un turno.

    Si la respuesta vino de la caché, no hubo llamada al proveedor: los tokens y el
    coste de este turno son 0 y ``cache_hit_kind`` vale ``"exact"``. La caché
    semántica no existe en esta base, así que ese valor nunca se emite.

    :param session_id: Identificador de la sesión a la que pertenece el turno.
    :param turn_index: Número del turno dentro de la sesión, contado desde 1.
    :param enriched_transcript_chars: Longitud del mensaje del usuario, adjuntos incluidos.
    :param attachments_total_chars: Suma de caracteres extraídos de los adjuntos; 0 si no hay.
    :param messages_in_window: Mensajes que quedan en la ventana tras la compresión.
    :param anchors_count: Número de anclas heurísticas; 0 en esta base.
    :param summary_chars: Longitud del resumen acumulado; 0 en esta base.
    :param result: Respuesta normalizada del wrapper, con ``usage``, ``cost_usd`` y ``cache_hit``.
    :param latency_ms: Latencia medida alrededor de la llamada al wrapper, en milisegundos.
    :param last_resolved_tier: Tier resuelto por la regla dinámica, o ``None`` si no existe.
    :returns: Diccionario con las claves del evento, listo para ``log.info`` y para el CSV.
    :raises ValueError: Si ``turn_index`` es menor que 1.
    """
    if turn_index < 1:
        raise ValueError("turn_index es 1-based y debe ser al menos 1")

    cache_hit = bool(result.get("cache_hit"))
    usage = result.get("usage") or {}
    return {
        "turn_index": turn_index,
        "session_id": session_id,
        "enriched_transcript_chars": enriched_transcript_chars,
        "attachments_total_chars": attachments_total_chars,
        "messages_in_window": messages_in_window,
        "anchors_count": anchors_count,
        "summary_chars": summary_chars,
        "tokens_in": 0 if cache_hit else int(usage.get("input_tokens", 0)),
        "tokens_out": 0 if cache_hit else int(usage.get("output_tokens", 0)),
        "cost_usd": 0.0 if cache_hit else float(result.get("cost_usd", 0.0)),
        "latency_ms": latency_ms,
        "cache_hit_kind": "exact" if cache_hit else "none",
        "last_resolved_tier": last_resolved_tier,
    }
