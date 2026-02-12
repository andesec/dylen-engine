from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Job(Base):
  __tablename__ = "jobs"
  __table_args__ = (
    UniqueConstraint("user_id", "job_kind", "idempotency_key", name="ux_jobs_user_kind_idempotency"),
    Index("ux_jobs_active_resume_source", "resume_source_job_id", unique=True, postgresql_where=text("resume_source_job_id IS NOT NULL AND status IN ('queued', 'running')")),
  )

  job_id: Mapped[str] = mapped_column(String, primary_key=True)
  root_job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  resume_source_job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  superseded_by_job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  job_kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
  request_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
  status: Mapped[str] = mapped_column(String, nullable=False)
  parent_job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  lesson_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
  section_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
  target_agent: Mapped[str | None] = mapped_column(String, nullable=True)
  result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  error_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  created_at: Mapped[str] = mapped_column(String, nullable=False, server_default=text("""to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD"T"HH24:MI:SS"Z"')"""))
  started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
  updated_at: Mapped[str] = mapped_column(String, nullable=False, server_default=text("""to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD"T"HH24:MI:SS"Z"')"""))
  completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
  idempotency_key: Mapped[str] = mapped_column(String, nullable=False, index=True)


class JobCheckpoint(Base):
  __tablename__ = "job_checkpoints"
  __table_args__ = (
    Index("ux_job_checkpoints_job_stage_section_not_null", "job_id", "stage", "section_index", unique=True, postgresql_where=text("section_index IS NOT NULL")),
    Index("ux_job_checkpoints_job_stage_null", "job_id", "stage", unique=True, postgresql_where=text("section_index IS NULL")),
  )

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True)
  stage: Mapped[str] = mapped_column(String, nullable=False)
  section_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
  state: Mapped[str] = mapped_column(String, nullable=False, index=True)
  artifact_refs_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
  updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class JobEvent(Base):
  __tablename__ = "job_events"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  job_id: Mapped[str] = mapped_column(ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False, index=True)
  event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
  message: Mapped[str] = mapped_column(Text, nullable=False)
  payload_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
