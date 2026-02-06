"""Storage interfaces and records for lesson persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SectionRecord:
  """Record stored in the sections table."""

  section_id: str
  lesson_id: str
  title: str
  order_index: int
  status: str
  content: dict[str, Any] | None


@dataclass(frozen=True)
class LessonRecord:
  """Record stored in the lessons repository."""

  lesson_id: str
  user_id: str | None
  topic: str
  title: str
  created_at: str
  schema_version: str
  prompt_version: str
  provider_a: str
  model_a: str
  provider_b: str
  model_b: str
  status: str
  latency_ms: int
  is_archived: bool = False
  idempotency_key: str | None = None
  tags: set[str] | None = None


class LessonsRepository(Protocol):
  """Repository contract for lesson persistence."""

  async def create_lesson(self, record: LessonRecord) -> None:
    """Persist a lesson record."""

  async def create_sections(self, records: list[SectionRecord]) -> None:
    """Persist section records."""

  async def get_lesson(self, lesson_id: str) -> LessonRecord | None:
    """Fetch a lesson record by lesson identifier."""

  async def list_sections(self, lesson_id: str) -> list[SectionRecord]:
    """List all sections for a lesson."""

  async def update_lesson_title(self, lesson_id: str, title: str) -> None:
    """Update an existing lesson's title."""

  async def list_lessons(self, limit: int, offset: int, topic: str | None = None, status: str | None = None) -> tuple[list[LessonRecord], int]:
    """Return a paginated list of lessons with optional filters, and total count."""
