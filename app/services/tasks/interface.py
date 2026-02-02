from __future__ import annotations

from typing import Protocol


class TaskEnqueuer(Protocol):
  """Interface for enqueuing background tasks."""

  async def enqueue(self, job_id: str, payload: dict) -> None:
    """Enqueue a job for processing."""
    ...

  async def enqueue_lesson(self, lesson_id: str, job_id: str, params: dict, user_id: str) -> None:
    """Enqueue a lesson generation task."""
    ...
