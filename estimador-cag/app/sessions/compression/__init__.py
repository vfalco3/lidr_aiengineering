"""Compresión híbrida de conversaciones largas.

Fase 1: solo ``AnchorDetector`` (detección heurística de anclas).

Pendiente de la fase 2: ``CumulativeSummarizer`` (resumen acumulativo con LLM) y
``CompressionPolicy`` / ``apply_compression``, que dependen de los prompts y del
wrapper con salida estructurada.
"""

from app.sessions.compression.anchors import AnchorDetector, AnchorMatch

__all__ = ["AnchorDetector", "AnchorMatch"]
