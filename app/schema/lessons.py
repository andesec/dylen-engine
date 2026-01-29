from __future__ import annotations

from sqlalchemy import ARRAY, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Lesson(Base):
  __tablename__ = "dylen_lessons"

  lesson_id: Mapped[str] = mapped_column(String, primary_key=True)
  topic: Mapped[str] = mapped_column(String, nullable=False)
  title: Mapped[str] = mapped_column(String, nullable=False)
  created_at: Mapped[str] = mapped_column(String, nullable=False)  # Stored as text in legacy
  schema_version: Mapped[str] = mapped_column(String, nullable=False)
  prompt_version: Mapped[str] = mapped_column(String, nullable=False)
  provider_a: Mapped[str] = mapped_column(String, nullable=False)
  model_a: Mapped[str] = mapped_column(String, nullable=False)
  provider_b: Mapped[str] = mapped_column(String, nullable=False)
  model_b: Mapped[str] = mapped_column(String, nullable=False)
  lesson_json: Mapped[str] = mapped_column(Text, nullable=False)
  status: Mapped[str] = mapped_column(String, nullable=False)
  latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
  idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
