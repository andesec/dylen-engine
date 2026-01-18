"""Progress tracking scaffolding."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.progress.events import ProgressEvent

Metrics = dict[str, Any] | None
ProgressSink = Callable[[ProgressEvent], None] | None


class ProgressTracker:
    """Emit structured progress events to a sink."""

    def __init__(self, sink: ProgressSink = None) -> None:
        self._sink = sink

    def emit(
        self,
        *,
        phase: str,
        step: str | None = None,
        section_id: int | None = None,
        message: str | None = None,
        metrics: Metrics = None,
    ) -> ProgressEvent:
        """Emit and return a progress event."""
        payload = {
            "phase": phase,
            "step": step,
            "section_id": section_id,
            "message": message,
            "metrics": metrics,
            "timestamp": datetime.utcnow(),
        }
        event = ProgressEvent(**payload)
        if self._sink:
            self._sink(event)
        return event
