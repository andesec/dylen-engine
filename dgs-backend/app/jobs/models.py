"""Domain models for asynchronous lesson generation jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["queued", "running", "done", "error", "canceled"]


@dataclass
class JobRecord:
    """Represents a background lesson generation job."""

    job_id: str
    request: dict[str, Any]
    status: JobStatus
    created_at: str
    updated_at: str
    phase: str | None = None
    subphase: str | None = None
    total_steps: int | None = None
    completed_steps: int | None = None
    progress: float | None = None
    logs: list[str] = field(default_factory=list)
    result_json: dict[str, Any] | None = None
    artifacts: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None
    completed_at: str | None = None
    ttl: int | None = None
    idempotency_key: str | None = None
