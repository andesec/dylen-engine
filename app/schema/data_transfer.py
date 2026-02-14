"""SQLAlchemy model for export/hydrate transfer run tracking."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DataTransferRun(Base):
  """Persist admin-triggered export/hydrate runs and artifact references."""

  __tablename__ = "data_transfer_runs"
  __table_args__ = (UniqueConstraint("run_type", "requested_by", "idempotency_key", name="ux_data_transfer_runs_type_user_idempotency"),)

  id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
  job_id: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
  run_type: Mapped[str] = mapped_column(String, nullable=False, index=True)  # export | hydrate
  status: Mapped[str] = mapped_column(String, nullable=False, index=True)  # queued | running | done | error
  requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
  source_export_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("data_transfer_runs.id"), nullable=True, index=True)
  include_illustrations: Mapped[bool] = mapped_column(nullable=False, default=True)
  include_audios: Mapped[bool] = mapped_column(nullable=False, default=True)
  include_fensters: Mapped[bool] = mapped_column(nullable=False, default=True)
  separate_zips: Mapped[bool] = mapped_column(nullable=False, default=False)
  dry_run: Mapped[bool] = mapped_column(nullable=False, default=False)
  password_plaintext: Mapped[str] = mapped_column(Text, nullable=False)
  gcs_bucket: Mapped[str] = mapped_column(String, nullable=False)
  artifacts_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  filters_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
  result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
  started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
  completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
  idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
