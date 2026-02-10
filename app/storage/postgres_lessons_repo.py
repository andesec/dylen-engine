"""Postgres-backed repository for lesson persistence using SQLAlchemy."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.schema.lessons import Lesson, Section, SectionError
from app.storage.lessons_repo import LessonRecord, LessonsRepository, SectionErrorRecord, SectionRecord

logger = logging.getLogger(__name__)


class PostgresLessonsRepository(LessonsRepository):
  """Persist lessons to Postgres using SQLAlchemy."""

  def __init__(self, table_name: str = "lessons") -> None:
    # table_name is kept for signature compatibility but effectively defined by the Model
    self._session_factory = get_session_factory()
    if self._session_factory is None:
      raise RuntimeError("Database not initialized")

  async def create_lesson(self, record: LessonRecord) -> None:
    """Insert a lesson record."""
    async with self._session_factory() as session:
      tags = sorted(record.tags) if record.tags else None

      lesson = Lesson(
        lesson_id=record.lesson_id,
        user_id=record.user_id,
        topic=record.topic,
        title=record.title,
        created_at=record.created_at,
        schema_version=record.schema_version,
        prompt_version=record.prompt_version,
        provider_a=record.provider_a,
        model_a=record.model_a,
        provider_b=record.provider_b,
        model_b=record.model_b,
        status=record.status,
        latency_ms=record.latency_ms,
        idempotency_key=record.idempotency_key,
        tags=tags,
        is_archived=bool(record.is_archived),
        lesson_plan=record.lesson_plan,
      )
      session.add(lesson)
      await session.commit()

  async def upsert_lesson(self, record: LessonRecord) -> None:
    """Insert or update a lesson record."""
    async with self._session_factory() as session:
      lesson = await session.get(Lesson, record.lesson_id)
      tags = sorted(record.tags) if record.tags else None
      if not lesson:
        lesson = Lesson(lesson_id=record.lesson_id)
        session.add(lesson)

      lesson.user_id = record.user_id
      lesson.topic = record.topic
      lesson.title = record.title
      lesson.created_at = record.created_at
      lesson.schema_version = record.schema_version
      lesson.prompt_version = record.prompt_version
      lesson.provider_a = record.provider_a
      lesson.model_a = record.model_a
      lesson.provider_b = record.provider_b
      lesson.model_b = record.model_b
      lesson.status = record.status
      lesson.latency_ms = record.latency_ms
      lesson.idempotency_key = record.idempotency_key
      lesson.tags = tags
      lesson.is_archived = bool(record.is_archived)
      lesson.lesson_plan = record.lesson_plan

      await session.commit()

  async def create_sections(self, records: list[SectionRecord]) -> list[SectionRecord]:
    """Persist section records."""
    async with self._session_factory() as session:
      created_records: list[SectionRecord] = []
      for r in records:
        section = Section(lesson_id=r.lesson_id, title=r.title, order_index=r.order_index, status=r.status, content=r.content, content_shorthand=r.content_shorthand)
        session.add(section)
        await session.flush()
        created_records.append(SectionRecord(section_id=section.section_id, lesson_id=section.lesson_id, title=section.title, order_index=section.order_index, status=section.status, content=section.content, content_shorthand=section.content_shorthand))
      await session.commit()
      return created_records

  async def create_section_errors(self, records: list[SectionErrorRecord]) -> list[SectionErrorRecord]:
    """Persist section validation errors."""
    async with self._session_factory() as session:
      created_records: list[SectionErrorRecord] = []
      for r in records:
        if r.section_id is None:
          raise RuntimeError("Section error persistence requires a section_id.")
        section_error = SectionError(section_id=r.section_id, error_index=r.error_index, error_message=r.error_message, error_path=r.error_path, section_scope=r.section_scope, subsection_index=r.subsection_index, item_index=r.item_index)
        session.add(section_error)
        await session.flush()
        created_records.append(
          SectionErrorRecord(
            id=section_error.id,
            section_id=section_error.section_id,
            error_index=section_error.error_index,
            error_message=section_error.error_message,
            error_path=section_error.error_path,
            section_scope=section_error.section_scope,
            subsection_index=section_error.subsection_index,
            item_index=section_error.item_index,
          )
        )
      await session.commit()
      return created_records

  async def create_section_with_errors(self, section: SectionRecord, errors: list[SectionErrorRecord]) -> SectionRecord:
    """Persist one section and all associated validation errors atomically."""
    async with self._session_factory() as session:
      section_row = Section(lesson_id=section.lesson_id, title=section.title, order_index=section.order_index, status=section.status, content=section.content, content_shorthand=section.content_shorthand)
      session.add(section_row)
      await session.flush()
      if errors:
        for error in errors:
          if error.section_id is not None and error.section_id != section_row.section_id:
            raise RuntimeError("Section error section_id mismatch during atomic persistence.")
          section_error = SectionError(
            section_id=section_row.section_id, error_index=error.error_index, error_message=error.error_message, error_path=error.error_path, section_scope=error.section_scope, subsection_index=error.subsection_index, item_index=error.item_index
          )
          session.add(section_error)
      await session.commit()
      return SectionRecord(
        section_id=section_row.section_id, lesson_id=section_row.lesson_id, title=section_row.title, order_index=section_row.order_index, status=section_row.status, content=section_row.content, content_shorthand=section_row.content_shorthand
      )

  async def update_section_content_and_shorthand(self, section_id: int, content: dict[str, Any], content_shorthand: dict[str, Any]) -> None:
    """Update a section row with final content and shorthand payloads."""
    async with self._session_factory() as session:
      section = await session.get(Section, section_id)
      if section is None:
        raise RuntimeError(f"Section {section_id} not found for content update.")
      section.content = content
      section.content_shorthand = content_shorthand
      session.add(section)
      await session.commit()

  async def update_section_shorthand(self, section_id: int, content_shorthand: dict[str, Any]) -> None:
    """Update shorthand content for an existing section."""
    async with self._session_factory() as session:
      section = await session.get(Section, section_id)
      if section is None:
        raise RuntimeError(f"Section {section_id} not found for shorthand update.")
      section.content_shorthand = content_shorthand
      session.add(section)
      await session.commit()

  async def get_lesson(self, lesson_id: str, user_id: str | None = None) -> LessonRecord | None:
    """Fetch a lesson record by lesson identifier."""
    async with self._session_factory() as session:
      stmt = select(Lesson).where(Lesson.lesson_id == lesson_id)
      if user_id:
        stmt = stmt.where(Lesson.user_id == user_id)

      result = await session.execute(stmt)
      lesson = result.scalar_one_or_none()

      if not lesson:
        return None
      return self._model_to_record(lesson)

  async def list_sections(self, lesson_id: str) -> list[SectionRecord]:
    """List all sections for a lesson."""
    async with self._session_factory() as session:
      stmt = select(Section).where(Section.lesson_id == lesson_id).order_by(Section.order_index)
      result = await session.execute(stmt)
      sections = result.scalars().all()
      return [SectionRecord(section_id=s.section_id, lesson_id=s.lesson_id, title=s.title, order_index=s.order_index, status=s.status, content=s.content, content_shorthand=s.content_shorthand) for s in sections]

  async def update_lesson_title(self, lesson_id: str, title: str) -> None:
    """Update an existing lesson's title."""
    async with self._session_factory() as session:
      lesson = await session.get(Lesson, lesson_id)
      if not lesson:
        raise RuntimeError("Lesson not found.")
      if str(title).strip():
        lesson.title = str(title).strip()
      session.add(lesson)
      await session.commit()

  async def list_lessons(self, limit: int, offset: int, topic: str | None = None, status: str | None = None, user_id: str | None = None) -> tuple[list[LessonRecord], int]:
    """Return a paginated list of lessons with optional filters, and total count."""
    async with self._session_factory() as session:
      # Build query
      stmt = select(Lesson).order_by(Lesson.created_at.desc()).limit(limit).offset(offset)
      count_stmt = select(func.count()).select_from(Lesson)

      # Apply filters
      conditions = []
      if topic:
        conditions.append(Lesson.topic == topic)
      if status:
        conditions.append(Lesson.status == status)
      if user_id:
        conditions.append(Lesson.user_id == user_id)

      if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

      # Execute
      total = await session.scalar(count_stmt)
      result = await session.execute(stmt)
      lessons = result.scalars().all()

      return [self._model_to_record(lesson) for lesson in lessons], (total or 0)

  def _model_to_record(self, lesson: Lesson) -> LessonRecord:
    """Convert a SQLAlchemy model to a domain record."""
    tags = set(lesson.tags) if lesson.tags else None
    return LessonRecord(
      lesson_id=lesson.lesson_id,
      user_id=lesson.user_id,
      topic=lesson.topic,
      title=lesson.title,
      created_at=lesson.created_at,
      schema_version=lesson.schema_version,
      prompt_version=lesson.prompt_version,
      provider_a=lesson.provider_a,
      model_a=lesson.model_a,
      provider_b=lesson.provider_b,
      model_b=lesson.model_b,
      status=lesson.status,
      latency_ms=lesson.latency_ms,
      is_archived=bool(getattr(lesson, "is_archived", False)),
      idempotency_key=lesson.idempotency_key,
      tags=tags,
      lesson_plan=lesson.lesson_plan,
    )
