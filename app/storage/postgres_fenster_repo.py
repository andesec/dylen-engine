"""Repository for fenster widget data access using PostgreSQL."""

from __future__ import annotations

import uuid

import msgspec
from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.schema.fenster import FensterWidget, FensterWidgetType


class FensterRecord(msgspec.Struct):
  """Fenster widget record for API responses."""

  fenster_id: str
  type: str
  url: str | None
  has_content: bool  # True if content blob exists
  content_size_bytes: int | None  # Size of compressed content
  created_at: str


class PostgresFensterRepository:
  """Persist and retrieve fenster widgets from Postgres using SQLAlchemy."""

  def __init__(self, table_name: str = "fenster_widgets") -> None:
    self._session_factory = get_session_factory()
    if self._session_factory is None:
      raise RuntimeError("Database not initialized")

  async def list_fenster(self, page: int = 1, limit: int = 20, fenster_id: str | None = None, widget_type: str | None = None, sort_by: str = "created_at", sort_order: str = "desc") -> tuple[list[FensterRecord], int]:
    """Return a paginated list of fenster widgets with filters, sorting, and total count."""
    async with self._session_factory() as session:
      # Calculate offset from page
      offset = (page - 1) * limit

      # Build base query
      stmt = select(FensterWidget).limit(limit).offset(offset)
      count_stmt = select(func.count()).select_from(FensterWidget)

      # Apply filters
      conditions = []
      if fenster_id:
        try:
          parsed_id = uuid.UUID(fenster_id)
          conditions.append(FensterWidget.fenster_id == parsed_id)
        except ValueError:
          pass  # Invalid UUID, skip filter
      if widget_type:
        try:
          type_enum = FensterWidgetType(widget_type)
          conditions.append(FensterWidget.type == type_enum)
        except ValueError:
          pass  # Invalid type, skip filter

      if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

      # Apply sorting
      sort_column = FensterWidget.created_at  # default
      if sort_by == "fenster_id":
        sort_column = FensterWidget.fenster_id
      elif sort_by == "type":
        sort_column = FensterWidget.type
      elif sort_by == "created_at":
        sort_column = FensterWidget.created_at

      if sort_order.lower() == "asc":
        stmt = stmt.order_by(sort_column.asc())
      else:
        stmt = stmt.order_by(sort_column.desc())

      # Execute queries
      total = await session.scalar(count_stmt)
      result = await session.execute(stmt)
      widgets = result.scalars().all()

      records = []
      for widget in widgets:
        records.append(
          FensterRecord(fenster_id=str(widget.fenster_id), type=widget.type.value, url=widget.url, has_content=widget.content is not None, content_size_bytes=len(widget.content) if widget.content else None, created_at=widget.created_at.isoformat())
        )

      return records, (total or 0)
