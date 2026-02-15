from __future__ import annotations

import datetime
from enum import Enum as PyEnum

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SubsectionWidgetType(str, PyEnum):
  MARKDOWN = "markdown"
  FLIPCARDS = "flipcards"
  TR = "tr"
  FILLBLANK = "fillblank"
  TABLE = "table"
  COMPARE = "compare"
  SWIPECARDS = "swipecards"
  FREETEXT = "freeText"
  INPUTLINE = "inputLine"
  STEPFLOW = "stepFlow"
  ASCIIDIAGRAM = "asciiDiagram"
  CHECKLIST = "checklist"
  INTERACTIVETERMINAL = "interactiveTerminal"
  TERMINALDEMO = "terminalDemo"
  CODEEDITOR = "codeEditor"
  TREEVIEW = "treeview"
  MCQS = "mcqs"
  FENSTER = "fenster"
  ILLUSTRATION = "illustration"


def _subsection_widget_type_values(enum_cls: type[PyEnum]) -> list[str]:
  """Persist enum values (e.g. `markdown`) instead of enum names (e.g. `MARKDOWN`)."""
  return [str(member.value) for member in enum_cls]


class Lesson(Base):
  __tablename__ = "lessons"

  lesson_id: Mapped[str] = mapped_column(String, primary_key=True)
  user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  topic: Mapped[str] = mapped_column(String, nullable=False)
  title: Mapped[str] = mapped_column(String, nullable=False)
  created_at: Mapped[str] = mapped_column(String, nullable=False, server_default=text("""to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD"T"HH24:MI:SS"Z"')"""))  # Stored as text in legacy
  schema_version: Mapped[str] = mapped_column(String, nullable=False)
  prompt_version: Mapped[str] = mapped_column(String, nullable=False)
  provider_a: Mapped[str] = mapped_column(String, nullable=False)
  model_a: Mapped[str] = mapped_column(String, nullable=False)
  provider_b: Mapped[str] = mapped_column(String, nullable=False)
  model_b: Mapped[str] = mapped_column(String, nullable=False)
  # lesson_json removed
  lesson_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  lesson_request_id: Mapped[int | None] = mapped_column(ForeignKey("lesson_requests.id"), nullable=True, index=True)
  status: Mapped[str] = mapped_column(String, nullable=False)
  latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
  idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
  is_archived: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")

  sections: Mapped[list[Section]] = relationship("Section", back_populates="lesson", cascade="all, delete-orphan")


class Section(Base):
  __tablename__ = "sections"
  __table_args__ = (UniqueConstraint("lesson_id", "order_index", name="ux_sections_lesson_order_index"),)

  section_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.lesson_id"), nullable=False, index=True)
  title: Mapped[str] = mapped_column(String, nullable=False)
  order_index: Mapped[int] = mapped_column(Integer, nullable=False)
  status: Mapped[str] = mapped_column(String, nullable=False)
  content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  content_shorthand: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  removed_widgets_csv: Mapped[str | None] = mapped_column(Text, nullable=True)
  illustration_id: Mapped[int | None] = mapped_column(ForeignKey("illustrations.id", ondelete="SET NULL"), nullable=True, index=True)
  markdown_id: Mapped[int | None] = mapped_column(ForeignKey("markdowns.id", ondelete="SET NULL"), nullable=True, index=True)
  tutor_id: Mapped[int | None] = mapped_column(ForeignKey("tutors.id", ondelete="SET NULL"), nullable=True, index=True)

  lesson: Mapped[Lesson] = relationship("Lesson", back_populates="sections")
  errors: Mapped[list[SectionError]] = relationship("SectionError", back_populates="section", cascade="all, delete-orphan")
  subsections: Mapped[list[Subsection]] = relationship("Subsection", back_populates="section", cascade="all, delete-orphan")


class SectionError(Base):
  __tablename__ = "section_errors"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  section_id: Mapped[int] = mapped_column(ForeignKey("sections.section_id", ondelete="CASCADE"), nullable=False, index=True)
  error_index: Mapped[int] = mapped_column(Integer, nullable=False)
  error_message: Mapped[str] = mapped_column(Text, nullable=False)
  error_path: Mapped[str | None] = mapped_column(Text, nullable=True)
  section_scope: Mapped[str | None] = mapped_column(String, nullable=True)
  subsection_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
  item_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

  section: Mapped[Section] = relationship("Section", back_populates="errors")


class Subsection(Base):
  __tablename__ = "subsections"
  __table_args__ = (UniqueConstraint("section_id", "index", name="ux_subsections_section_subsection_index"),)

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  section_id: Mapped[int] = mapped_column(ForeignKey("sections.section_id", ondelete="CASCADE"), nullable=False, index=True)
  index: Mapped[int] = mapped_column(Integer, nullable=False)
  title: Mapped[str] = mapped_column(Text, nullable=False)
  status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
  is_archived: Mapped[bool] = mapped_column(default=False, nullable=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

  section: Mapped[Section] = relationship("Section", back_populates="subsections")
  widgets: Mapped[list[SubsectionWidget]] = relationship("SubsectionWidget", back_populates="subsection", cascade="all, delete-orphan")


class SubsectionWidget(Base):
  __tablename__ = "subsection_widgets"
  __table_args__ = (UniqueConstraint("subsection_id", "widget_index", "widget_type", name="ux_subsection_widgets_subsection_widget_index_type"), UniqueConstraint("public_id", name="ux_subsection_widgets_public_id"))

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  public_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  subsection_id: Mapped[int] = mapped_column(ForeignKey("subsections.id", ondelete="CASCADE"), nullable=False, index=True)
  widget_id: Mapped[str | None] = mapped_column(String, nullable=True)
  widget_index: Mapped[int] = mapped_column(Integer, nullable=False)
  widget_type: Mapped[SubsectionWidgetType] = mapped_column(SAEnum(SubsectionWidgetType, name="subsection_widget_type", values_callable=_subsection_widget_type_values, validate_strings=True), nullable=False)
  status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
  is_archived: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

  subsection: Mapped[Subsection] = relationship("Subsection", back_populates="widgets")


class InputLine(Base):
  __tablename__ = "input_lines"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  creator_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  ai_prompt: Mapped[str] = mapped_column(Text, nullable=False)
  wordlist: Mapped[str | None] = mapped_column(Text, nullable=True)
  is_archived: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FreeText(Base):
  __tablename__ = "free_texts"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  creator_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  ai_prompt: Mapped[str] = mapped_column(Text, nullable=False)
  wordlist: Mapped[str | None] = mapped_column(Text, nullable=True)
  is_archived: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
