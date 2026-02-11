"""Storage interfaces and records for lesson persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SectionRecord:
  """Record stored in the sections table."""

  section_id: int | None
  lesson_id: str
  title: str
  order_index: int
  status: str
  content: dict[str, Any] | None
  content_shorthand: dict[str, Any] | None = None
  removed_widgets_csv: str | None = None
  illustration_id: int | None = None
  markdown_id: int | None = None
  tutor_id: int | None = None


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
  lesson_plan: dict[str, Any] | None = None
  lesson_request_id: int | None = None


@dataclass(frozen=True)
class SectionErrorRecord:
  """Validation error persisted for a generated section."""

  id: int | None
  section_id: int | None
  error_index: int
  error_message: str
  error_path: str | None = None
  section_scope: str | None = None
  subsection_index: int | None = None
  item_index: int | None = None


@dataclass(frozen=True)
class InputLineRecord:
  """Record stored in the input_lines table."""

  id: int | None
  creator_id: str
  ai_prompt: str
  wordlist: str | None = None
  created_at: str | None = None


@dataclass(frozen=True)
class FreeTextRecord:
  """Record stored in the free_texts table."""

  id: int | None
  creator_id: str
  ai_prompt: str
  wordlist: str | None = None
  created_at: str | None = None


@dataclass(frozen=True)
class SubsectionRecord:
  """Record stored in the subsections table."""

  id: int | None
  section_id: int
  subsection_index: int
  subsection_title: str
  status: str = "pending"
  is_archived: bool = False


@dataclass(frozen=True)
class SubsectionWidgetRecord:
  """Record stored in the subsection_widgets table."""

  subsection_id: int
  widget_index: int
  widget_type: str
  id: int | None = None
  public_id: str | None = None
  widget_id: str | None = None
  status: str = "pending"
  is_archived: bool = False


class LessonsRepository(Protocol):
  """Repository contract for lesson persistence."""

  async def create_lesson(self, record: LessonRecord) -> None:
    """Persist a lesson record."""

  async def upsert_lesson(self, record: LessonRecord) -> None:
    """Insert or update a lesson record."""

  async def create_sections(self, records: list[SectionRecord]) -> list[SectionRecord]:
    """Persist section records."""

  async def create_input_lines(self, records: list[InputLineRecord]) -> list[InputLineRecord]:
    """Persist input line records."""

  async def create_free_texts(self, records: list[FreeTextRecord]) -> list[FreeTextRecord]:
    """Persist free text records."""

  async def create_subsections(self, records: list[SubsectionRecord]) -> list[SubsectionRecord]:
    """Persist subsection records."""

  async def create_subsection_widgets(self, records: list[SubsectionWidgetRecord]) -> list[SubsectionWidgetRecord]:
    """Persist subsection widget records."""

  async def create_widget_payload(self, *, widget_type: str, creator_id: str, payload_json: dict[str, Any]) -> str:
    """Persist a typed widget payload and return persisted widget row id."""

  async def create_section_errors(self, records: list[SectionErrorRecord]) -> list[SectionErrorRecord]:
    """Persist section validation errors."""

  async def create_section_with_errors(self, section: SectionRecord, errors: list[SectionErrorRecord]) -> SectionRecord:
    """Persist one section and its validation errors atomically."""

  async def update_section_content_and_shorthand(self, section_id: int, content: dict[str, Any], content_shorthand: dict[str, Any]) -> None:
    """Update a section row with final content and shorthand payloads."""

  async def update_section_shorthand(self, section_id: int, content_shorthand: dict[str, Any]) -> None:
    """Update only shorthand content for an existing section."""

  async def update_section_links(self, section_id: int, *, markdown_id: int | None = None, illustration_id: int | None = None, tutor_id: int | None = None) -> None:
    """Update section-level foreign-key links for persisted artifacts."""

  async def get_lesson(self, lesson_id: str, user_id: str | None = None) -> LessonRecord | None:
    """Fetch a lesson record by lesson identifier."""

  async def list_sections(self, lesson_id: str) -> list[SectionRecord]:
    """List all sections for a lesson."""

  async def update_lesson_title(self, lesson_id: str, title: str) -> None:
    """Update an existing lesson's title."""

  async def list_lessons(self, limit: int, offset: int, topic: str | None = None, status: str | None = None, user_id: str | None = None) -> tuple[list[LessonRecord], int]:
    """Return a paginated list of lessons with optional filters, and total count."""
