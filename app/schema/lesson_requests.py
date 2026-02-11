from __future__ import annotations

import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LessonRequest(Base):
  __tablename__ = "lesson_requests"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  creator_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  topic: Mapped[str] = mapped_column(Text, nullable=False)
  details: Mapped[str | None] = mapped_column(Text, nullable=True)
  outcomes_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
  blueprint: Mapped[str] = mapped_column(String, nullable=False)
  teaching_style_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
  learner_level: Mapped[str | None] = mapped_column(String, nullable=True)
  depth: Mapped[str] = mapped_column(String, nullable=False)
  lesson_language: Mapped[str] = mapped_column(String, nullable=False)
  secondary_language: Mapped[str | None] = mapped_column(String, nullable=True)
  widgets_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
  status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
  is_archived: Mapped[bool] = mapped_column(nullable=False, default=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
