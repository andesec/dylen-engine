"""Storage interfaces and records for lesson persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LessonRecord:
  """Record stored in the lessons repository."""

  lesson_id: str
  topic: str
  title: str
  created_at: str
  schema_version: str
  prompt_version: str
  provider_a: str
  model_a: str
  provider_b: str
  model_b: str
  lesson_json: str
  status: str
  latency_ms: int
  idempotency_key: str | None = None
  tags: set[str] | None = None


class LessonsRepository(Protocol):
  """Repository contract for lesson persistence."""

  def create_lesson(self, record: LessonRecord) -> None:
    """Persist a lesson record."""

  def get_lesson(self, lesson_id: str) -> LessonRecord | None:
    """Fetch a lesson record by lesson identifier."""
