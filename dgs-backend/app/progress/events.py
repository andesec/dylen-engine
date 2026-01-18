"""Progress event definitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ProgressEvent:
    """Structured progress event emitted during generation."""

    phase: str
    step: str | None
    section_id: int | None
    message: str | None
    metrics: dict[str, Any] | None
    timestamp: datetime

    def as_dict(self) -> dict[str, Any]:
        """Serialize the event for logging or persistence."""
        return {
            "phase": self.phase,
            "step": self.step,
            "section_id": self.section_id,
            "message": self.message,
            "metrics": self.metrics,
            "timestamp": self.timestamp.isoformat(),
        }
