"""Repository for illustration data access using PostgreSQL."""

from __future__ import annotations

import msgspec
from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.schema.illustrations import Illustration
from app.schema.lessons import Section


class IllustrationRecord(msgspec.Struct):
  """Illustration record for API responses."""

  id: int
  storage_bucket: str
  storage_object_name: str
  mime_type: str
  caption: str
  ai_prompt: str
  keywords: list[str]
  status: str
  is_archived: bool
  regenerate: bool
  created_at: str
  updated_at: str
  section_ids: list[int]  # Associated section IDs
  lesson_ids: list[str]  # Associated lesson IDs


class PostgresIllustrationsRepository:
  """Persist and retrieve illustrations from Postgres using SQLAlchemy."""

  def __init__(self, table_name: str = "illustrations") -> None:
    self._session_factory = get_session_factory()
    if self._session_factory is None:
      raise RuntimeError("Database not initialized")

  async def list_illustrations(
    self, page: int = 1, limit: int = 20, status: str | None = None, is_archived: bool | None = None, mime_type: str | None = None, section_id: int | None = None, sort_by: str = "created_at", sort_order: str = "desc"
  ) -> tuple[list[IllustrationRecord], int]:
    """Return a paginated list of illustrations with filters, sorting, and total count."""
    async with self._session_factory() as session:
      # Calculate offset from page
      offset = (page - 1) * limit

      # Build base query
      stmt = select(Illustration).limit(limit).offset(offset)
      count_stmt = select(func.count()).select_from(Illustration)

      # Apply filters
      conditions = []
      if status:
        conditions.append(Illustration.status == status)
      if is_archived is not None:
        conditions.append(Illustration.is_archived == is_archived)
      if mime_type:
        conditions.append(Illustration.mime_type == mime_type)
      if section_id is not None:
        stmt = stmt.join(Section, Section.illustration_id == Illustration.id).where(Section.section_id == section_id)
        count_stmt = count_stmt.join(Section, Section.illustration_id == Illustration.id).where(Section.section_id == section_id)

      if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

      # Apply sorting
      sort_column = Illustration.created_at  # default
      if sort_by == "id":
        sort_column = Illustration.id
      elif sort_by == "created_at":
        sort_column = Illustration.created_at
      elif sort_by == "status":
        sort_column = Illustration.status
      elif sort_by == "caption":
        sort_column = Illustration.caption

      if sort_order.lower() == "asc":
        stmt = stmt.order_by(sort_column.asc())
      else:
        stmt = stmt.order_by(sort_column.desc())

      # Execute queries
      total = await session.scalar(count_stmt)
      result = await session.execute(stmt)
      illustrations = result.scalars().all()

      # Fetch associated sections and lessons for each illustration
      records = []
      for illustration in illustrations:
        # Get section IDs
        section_stmt = select(Section.section_id).where(Section.illustration_id == illustration.id)
        section_result = await session.execute(section_stmt)
        section_ids = [row[0] for row in section_result.all()]

        # Get lesson IDs from sections
        lesson_ids = []
        if section_ids:
          lesson_stmt = select(Section.lesson_id).where(Section.section_id.in_(section_ids)).distinct()
          lesson_result = await session.execute(lesson_stmt)
          lesson_ids = [row[0] for row in lesson_result.all()]

        records.append(
          IllustrationRecord(
            id=illustration.id,
            storage_bucket=illustration.storage_bucket,
            storage_object_name=illustration.storage_object_name,
            mime_type=illustration.mime_type,
            caption=illustration.caption,
            ai_prompt=illustration.ai_prompt,
            keywords=illustration.keywords,
            status=illustration.status,
            is_archived=illustration.is_archived,
            regenerate=illustration.regenerate,
            created_at=illustration.created_at.isoformat(),
            updated_at=illustration.updated_at.isoformat(),
            section_ids=section_ids,
            lesson_ids=lesson_ids,
          )
        )

      return records, (total or 0)
