from __future__ import annotations

from typing import Protocol


class TaskEnqueuer(Protocol):
  """Interface for enqueuing background tasks."""

  async def enqueue(self, job_id: str, payload: dict) -> None:
    """Enqueue a job for processing."""
    ...
