"""Postgres-backed repository for lesson persistence using SQLAlchemy."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.schema.fenster import FensterWidget, FensterWidgetType
from app.schema.lessons import FreeText, InputLine, Lesson, Section, SectionError, Subsection, SubsectionWidget
from app.schema.widgets_content import (
  AsciiDiagramWidget,
  ChecklistWidget,
  CodeEditorWidget,
  CompareWidget,
  FillBlankWidget,
  FlipcardsWidget,
  InteractiveTerminalWidget,
  MarkdownWidget,
  McqsWidget,
  StepFlowWidget,
  SwipeCardWidget,
  TableDataWidget,
  TerminalDemoWidget,
  TranslationWidget,
  TreeviewWidget,
)
from app.storage.lessons_repo import FreeTextRecord, InputLineRecord, LessonRecord, LessonsRepository, SectionErrorRecord, SectionRecord, SubsectionRecord, SubsectionWidgetRecord
from app.utils.ids import generate_nanoid

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
        lesson_request_id=record.lesson_request_id,
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
      lesson.lesson_request_id = record.lesson_request_id

      await session.commit()

  async def create_sections(self, records: list[SectionRecord]) -> list[SectionRecord]:
    """Persist section records."""
    async with self._session_factory() as session:
      created_records: list[SectionRecord] = []
      for r in records:
        existing = (await session.execute(select(Section).where(Section.lesson_id == r.lesson_id, Section.order_index == r.order_index).limit(1))).scalar_one_or_none()
        section = existing or Section(lesson_id=r.lesson_id, order_index=r.order_index)
        section.title = r.title
        section.status = r.status
        section.content = r.content
        section.content_shorthand = r.content_shorthand
        section.removed_widgets_csv = r.removed_widgets_csv
        section.illustration_id = r.illustration_id
        section.markdown_id = r.markdown_id
        section.tutor_id = r.tutor_id
        session.add(section)
        await session.flush()
        created_records.append(
          SectionRecord(
            section_id=section.section_id,
            lesson_id=section.lesson_id,
            title=section.title,
            order_index=section.order_index,
            status=section.status,
            content=section.content,
            content_shorthand=section.content_shorthand,
            removed_widgets_csv=section.removed_widgets_csv,
            illustration_id=section.illustration_id,
            markdown_id=section.markdown_id,
            tutor_id=section.tutor_id,
          )
        )
      await session.commit()
      return created_records

  async def create_input_lines(self, records: list[InputLineRecord]) -> list[InputLineRecord]:
    """Persist input line records."""
    async with self._session_factory() as session:
      if not records:
        created_records: list[InputLineRecord] = []
      else:
        db_widgets = [InputLine(creator_id=r.creator_id, ai_prompt=r.ai_prompt, wordlist=r.wordlist, is_archived=False) for r in records]
        session.add_all(db_widgets)
        await session.flush()
        created_records = [InputLineRecord(id=widget.id, creator_id=widget.creator_id, ai_prompt=widget.ai_prompt, wordlist=widget.wordlist, created_at=str(widget.created_at)) for widget in db_widgets]
      await session.commit()
      return created_records

  async def create_free_texts(self, records: list[FreeTextRecord]) -> list[FreeTextRecord]:
    """Persist free text records."""
    async with self._session_factory() as session:
      if not records:
        created_records: list[FreeTextRecord] = []
      else:
        db_widgets = [FreeText(creator_id=r.creator_id, ai_prompt=r.ai_prompt, wordlist=r.wordlist, is_archived=False) for r in records]
        session.add_all(db_widgets)
        await session.flush()
        created_records = [FreeTextRecord(id=widget.id, creator_id=widget.creator_id, ai_prompt=widget.ai_prompt, wordlist=widget.wordlist, created_at=str(widget.created_at)) for widget in db_widgets]
      await session.commit()
      return created_records

  async def create_subsections(self, records: list[SubsectionRecord]) -> list[SubsectionRecord]:
    """Persist subsection records."""
    async with self._session_factory() as session:
      created_records: list[SubsectionRecord] = []
      for r in records:
        subsection = (await session.execute(select(Subsection).where(Subsection.section_id == r.section_id, Subsection.subsection_index == r.subsection_index).limit(1))).scalar_one_or_none()
        if subsection is None:
          subsection = Subsection(section_id=r.section_id, subsection_index=r.subsection_index, subsection_title=r.subsection_title, status=r.status, is_archived=r.is_archived)
        else:
          subsection.subsection_title = r.subsection_title
          subsection.status = r.status
          subsection.is_archived = r.is_archived
        session.add(subsection)
        await session.flush()
        created_records.append(SubsectionRecord(id=subsection.id, section_id=subsection.section_id, subsection_index=subsection.subsection_index, subsection_title=subsection.subsection_title, status=subsection.status, is_archived=subsection.is_archived))
      await session.commit()
      return created_records

  async def create_subsection_widgets(self, records: list[SubsectionWidgetRecord]) -> list[SubsectionWidgetRecord]:
    """Persist subsection widget records."""
    async with self._session_factory() as session:
      created_records: list[SubsectionWidgetRecord] = []
      for r in records:
        widget = (await session.execute(select(SubsectionWidget).where(SubsectionWidget.subsection_id == r.subsection_id, SubsectionWidget.widget_index == r.widget_index, SubsectionWidget.widget_type == r.widget_type).limit(1))).scalar_one_or_none()
        public_id = str(r.public_id or generate_nanoid())
        if widget is None:
          widget = SubsectionWidget(public_id=public_id, subsection_id=r.subsection_id, widget_id=r.widget_id, widget_index=r.widget_index, widget_type=r.widget_type, status=r.status, is_archived=r.is_archived)
        else:
          widget.public_id = str(widget.public_id or public_id)
          widget.widget_id = r.widget_id
          widget.status = r.status
          widget.is_archived = r.is_archived
        session.add(widget)
        await session.flush()
        created_records.append(
          SubsectionWidgetRecord(
            id=widget.id, public_id=widget.public_id, subsection_id=widget.subsection_id, widget_id=widget.widget_id, widget_index=widget.widget_index, widget_type=widget.widget_type, status=widget.status, is_archived=widget.is_archived
          )
        )
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
      section_row = Section(
        lesson_id=section.lesson_id,
        title=section.title,
        order_index=section.order_index,
        status=section.status,
        content=section.content,
        content_shorthand=section.content_shorthand,
        removed_widgets_csv=section.removed_widgets_csv,
        illustration_id=section.illustration_id,
        markdown_id=section.markdown_id,
        tutor_id=section.tutor_id,
      )
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
        section_id=section_row.section_id,
        lesson_id=section_row.lesson_id,
        title=section_row.title,
        order_index=section_row.order_index,
        status=section_row.status,
        content=section_row.content,
        content_shorthand=section_row.content_shorthand,
        removed_widgets_csv=section_row.removed_widgets_csv,
        illustration_id=section_row.illustration_id,
        markdown_id=section_row.markdown_id,
        tutor_id=section_row.tutor_id,
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

  async def update_section_links(self, section_id: int, *, markdown_id: int | None = None, illustration_id: int | None = None, tutor_id: int | None = None) -> None:
    """Update section-level FK links for persisted artifacts."""
    async with self._session_factory() as session:
      section = await session.get(Section, section_id)
      if section is None:
        raise RuntimeError(f"Section {section_id} not found for link update.")
      if markdown_id is not None:
        section.markdown_id = int(markdown_id)
      if illustration_id is not None:
        section.illustration_id = int(illustration_id)
      if tutor_id is not None:
        section.tutor_id = int(tutor_id)
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
      return [
        SectionRecord(
          section_id=s.section_id,
          lesson_id=s.lesson_id,
          title=s.title,
          order_index=s.order_index,
          status=s.status,
          content=s.content,
          content_shorthand=s.content_shorthand,
          removed_widgets_csv=s.removed_widgets_csv,
          illustration_id=s.illustration_id,
          markdown_id=s.markdown_id,
          tutor_id=s.tutor_id,
        )
        for s in sections
      ]

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

  async def list_lessons(
    self, page: int = 1, limit: int = 20, topic: str | None = None, status: str | None = None, user_id: str | None = None, is_archived: bool | None = None, sort_by: str = "created_at", sort_order: str = "desc"
  ) -> tuple[list[LessonRecord], int]:
    """Return a paginated list of lessons with optional filters, sorting, and total count."""
    async with self._session_factory() as session:
      # Calculate offset from page
      offset = (page - 1) * limit

      # Build base query
      stmt = select(Lesson).limit(limit).offset(offset)
      count_stmt = select(func.count()).select_from(Lesson)

      # Apply filters
      conditions = []
      if topic:
        conditions.append(Lesson.topic == topic)
      if status:
        conditions.append(Lesson.status == status)
      if user_id:
        conditions.append(Lesson.user_id == user_id)
      if is_archived is not None:
        conditions.append(Lesson.is_archived == is_archived)

      if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

      # Apply sorting
      sort_column = Lesson.created_at  # default
      if sort_by == "lesson_id":
        sort_column = Lesson.lesson_id
      elif sort_by == "created_at":
        sort_column = Lesson.created_at
      elif sort_by == "topic":
        sort_column = Lesson.topic
      elif sort_by == "title":
        sort_column = Lesson.title
      elif sort_by == "status":
        sort_column = Lesson.status

      if sort_order.lower() == "asc":
        stmt = stmt.order_by(sort_column.asc())
      else:
        stmt = stmt.order_by(sort_column.desc())

      # Execute queries
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
      lesson_request_id=lesson.lesson_request_id,
    )

  async def create_widget_payload(self, *, widget_type: str, creator_id: str, payload_json: dict[str, Any]) -> str:
    """Persist a widget payload in its typed table and return the typed row id."""
    model_map = {
      "markdown": MarkdownWidget,
      "flipcards": FlipcardsWidget,
      "tr": TranslationWidget,
      "fillblank": FillBlankWidget,
      "table": TableDataWidget,
      "compare": CompareWidget,
      "swipecards": SwipeCardWidget,
      "stepFlow": StepFlowWidget,
      "asciiDiagram": AsciiDiagramWidget,
      "checklist": ChecklistWidget,
      "interactiveTerminal": InteractiveTerminalWidget,
      "terminalDemo": TerminalDemoWidget,
      "codeEditor": CodeEditorWidget,
      "treeview": TreeviewWidget,
      "mcqs": McqsWidget,
    }
    if widget_type == "fenster":
      async with self._session_factory() as session:
        row = FensterWidget(public_id=generate_nanoid(), creator_id=creator_id, status="pending", is_archived=False, type=FensterWidgetType.INLINE_BLOB, content=None, url=None)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return str(row.public_id)
    model_cls = model_map.get(widget_type)
    if model_cls is None:
      raise RuntimeError(f"Unsupported widget type for persistence: {widget_type}")
    async with self._session_factory() as session:
      row = model_cls(creator_id=creator_id, is_archived=False, payload_json=payload_json)
      session.add(row)
      await session.commit()
      await session.refresh(row)
      return str(row.id)
