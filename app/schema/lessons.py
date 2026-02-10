from __future__ import annotations

import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Lesson(Base):
  __tablename__ = "lessons"

  lesson_id: Mapped[str] = mapped_column(String, primary_key=True)
  user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  topic: Mapped[str] = mapped_column(String, nullable=False)
  title: Mapped[str] = mapped_column(String, nullable=False)
  created_at: Mapped[str] = mapped_column(String, nullable=False)  # Stored as text in legacy
  schema_version: Mapped[str] = mapped_column(String, nullable=False)
  prompt_version: Mapped[str] = mapped_column(String, nullable=False)
  provider_a: Mapped[str] = mapped_column(String, nullable=False)
  model_a: Mapped[str] = mapped_column(String, nullable=False)
  provider_b: Mapped[str] = mapped_column(String, nullable=False)
  model_b: Mapped[str] = mapped_column(String, nullable=False)
  # lesson_json removed
  lesson_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  status: Mapped[str] = mapped_column(String, nullable=False)
  latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
  idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
  is_archived: Mapped[bool] = mapped_column(default=False, nullable=False)

  sections: Mapped[list[Section]] = relationship("Section", back_populates="lesson", cascade="all, delete-orphan")


class Section(Base):
  __tablename__ = "sections"

  section_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.lesson_id"), nullable=False, index=True)
  title: Mapped[str] = mapped_column(String, nullable=False)
  order_index: Mapped[int] = mapped_column(Integer, nullable=False)
  status: Mapped[str] = mapped_column(String, nullable=False)
  content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  content_shorthand: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

  lesson: Mapped[Lesson] = relationship("Lesson", back_populates="sections")
  errors: Mapped[list[SectionError]] = relationship("SectionError", back_populates="section", cascade="all, delete-orphan")


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


class SubjectiveInputWidget(Base):
  __tablename__ = "subjective_input_widgets"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  section_id: Mapped[int] = mapped_column(ForeignKey("sections.section_id", ondelete="CASCADE"), nullable=False, index=True)
  widget_type: Mapped[str] = mapped_column(String, nullable=False)
  ai_prompt: Mapped[str] = mapped_column(Text, nullable=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
