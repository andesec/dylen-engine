from __future__ import annotations

from sqlalchemy import Double, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Job(Base):
  __tablename__ = "jobs"

  job_id: Mapped[str] = mapped_column(String, primary_key=True)
  user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  request: Mapped[dict] = mapped_column(JSONB, nullable=False)
  status: Mapped[str] = mapped_column(String, nullable=False)
  target_agent: Mapped[str | None] = mapped_column(String, nullable=True)
  phase: Mapped[str] = mapped_column(String, nullable=False)
  subphase: Mapped[str | None] = mapped_column(String, nullable=True)
  expected_sections: Mapped[int | None] = mapped_column(Integer, nullable=True)
  completed_sections: Mapped[int | None] = mapped_column(Integer, nullable=True)
  completed_section_indexes: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
  current_section_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
  current_section_status: Mapped[str | None] = mapped_column(String, nullable=True)
  current_section_retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
  current_section_title: Mapped[str | None] = mapped_column(String, nullable=True)
  retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
  max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True)
  retry_sections: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
  retry_agents: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
  retry_parent_job_id: Mapped[str | None] = mapped_column(String, nullable=True)
  total_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
  completed_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
  progress: Mapped[float | None] = mapped_column(Double, nullable=True)
  logs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
  result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  artifacts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  validation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  cost: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  created_at: Mapped[str] = mapped_column(String, nullable=False)
  updated_at: Mapped[str] = mapped_column(String, nullable=False)
  completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
  ttl: Mapped[int | None] = mapped_column(Integer, nullable=True)
  idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
