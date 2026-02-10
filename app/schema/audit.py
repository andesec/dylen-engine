from __future__ import annotations

import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LlmCallAudit(Base):
  __tablename__ = "llm_call_audit"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=True)
  timestamp_request: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  timestamp_response: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
  started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
  agent: Mapped[str] = mapped_column(String, nullable=False)
  provider: Mapped[str] = mapped_column(String, nullable=False)
  model: Mapped[str] = mapped_column(String, nullable=False)
  lesson_topic: Mapped[str | None] = mapped_column(String, nullable=True)
  request_payload: Mapped[str] = mapped_column(Text, nullable=False)
  response_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
  prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
  completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
  total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
  request_type: Mapped[str] = mapped_column(String, nullable=False)
  purpose: Mapped[str | None] = mapped_column(String, nullable=True)
  call_index: Mapped[str | None] = mapped_column(String, nullable=True)
  job_id: Mapped[str | None] = mapped_column(String, nullable=True)
  status: Mapped[str] = mapped_column(String, nullable=False)
  error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
