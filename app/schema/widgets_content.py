from __future__ import annotations

import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class _WidgetContentBase(Base):
  """Shared storage fields for persisted widget payload rows."""

  __abstract__ = True

  id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
  creator_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
  is_archived: Mapped[bool] = mapped_column(nullable=False, default=False)
  payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MarkdownWidget(_WidgetContentBase):
  __tablename__ = "markdowns"


class FlipcardsWidget(_WidgetContentBase):
  __tablename__ = "flipcards"


class TranslationWidget(_WidgetContentBase):
  __tablename__ = "translations"


class FillBlankWidget(_WidgetContentBase):
  __tablename__ = "fill_blanks"


class TableDataWidget(_WidgetContentBase):
  __tablename__ = "tables_data"


class CompareWidget(_WidgetContentBase):
  __tablename__ = "compares"


class SwipeCardWidget(_WidgetContentBase):
  __tablename__ = "swipe_cards"


class StepFlowWidget(_WidgetContentBase):
  __tablename__ = "step_flows"


class AsciiDiagramWidget(_WidgetContentBase):
  __tablename__ = "ascii_diagrams"


class ChecklistWidget(_WidgetContentBase):
  __tablename__ = "checklists"


class InteractiveTerminalWidget(_WidgetContentBase):
  __tablename__ = "interactive_terminals"


class TerminalDemoWidget(_WidgetContentBase):
  __tablename__ = "terminal_demos"


class CodeEditorWidget(_WidgetContentBase):
  __tablename__ = "code_editors"


class TreeviewWidget(_WidgetContentBase):
  __tablename__ = "treeviews"


class McqsWidget(_WidgetContentBase):
  __tablename__ = "mcqs"


class TutorFragment(Base):
  """Future-use table for fragment-level tutor tracking."""

  __tablename__ = "tutor_fragments"

  id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
  tutor_id: Mapped[int] = mapped_column(ForeignKey("tutors.id", ondelete="CASCADE"), nullable=False, index=True)
  fragment_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
  section_id: Mapped[int | None] = mapped_column(ForeignKey("sections.section_id", ondelete="SET NULL"), nullable=True, index=True)
  subsection_id: Mapped[int | None] = mapped_column(ForeignKey("subsections.id", ondelete="SET NULL"), nullable=True, index=True)
  status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
  is_archived: Mapped[bool] = mapped_column(nullable=False, default=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
