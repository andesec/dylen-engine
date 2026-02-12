"""SQLAlchemy models for subscription tiers and per-user quota tracking."""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SubscriptionTier(Base):
  __tablename__ = "subscription_tiers"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
  is_tenant_tier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
  max_file_upload_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
  highest_lesson_depth: Mapped[str | None] = mapped_column(Enum("highlights", "detailed", "training", name="lesson_depth"), nullable=True)
  max_sections_per_lesson: Mapped[int | None] = mapped_column(Integer, nullable=True)
  file_upload_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  image_upload_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  gen_sections_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  research_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  concurrent_lesson_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1, server_default="1")
  concurrent_research_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1, server_default="1")
  concurrent_writing_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1, server_default="1")
  concurrent_tutor_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1, server_default="1")
  tutor_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
  tutor_voice_tier: Mapped[str | None] = mapped_column(String, nullable=True)


class UserTierOverride(Base):
  __tablename__ = "user_tier_overrides"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False)
  starts_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)
  expires_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
  max_file_upload_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)
  file_upload_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  image_upload_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  gen_sections_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  research_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
  concurrent_lesson_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
  concurrent_research_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
  concurrent_writing_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
  concurrent_tutor_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
  tutor_mode_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class UserUsageMetrics(Base):
  __tablename__ = "user_usage_metrics"

  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
  subscription_tier_id: Mapped[int] = mapped_column(ForeignKey("subscription_tiers.id"), nullable=False)
  files_uploaded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  images_uploaded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  sections_generated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  research_usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  last_updated: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserUsageLog(Base):
  __tablename__ = "user_usage_logs"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False)
  action_type: Mapped[str] = mapped_column(String, nullable=False)
  quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
  metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
  created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class QuotaPeriod(str, enum.Enum):
  """Supported period buckets for quota accounting."""

  WEEK = "WEEK"
  MONTH = "MONTH"


class UserQuotaBucket(Base):
  """Generic per-user per-period counters for quota enforcement."""

  __tablename__ = "user_quota_buckets"

  id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False)
  metric_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
  # Schema migrations own enum lifecycle; avoid create_all races attempting to re-create the type.
  period: Mapped[QuotaPeriod] = mapped_column(ENUM(QuotaPeriod, name="quota_period", create_type=False), nullable=False)
  period_start: Mapped[Date] = mapped_column(Date, nullable=False)
  used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
  reserved: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
  updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class UserQuotaReservation(Base):
  """Track reserved quota usage awaiting commit or release."""

  __tablename__ = "user_quota_reservations"
  __table_args__ = (UniqueConstraint("user_id", "metric_key", "period", "period_start", "job_id", "section_index", name="ux_quota_reservation_key"),)

  id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
  user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True, nullable=False)
  metric_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
  period: Mapped[QuotaPeriod] = mapped_column(ENUM(QuotaPeriod, name="quota_period", create_type=False), nullable=False)
  period_start: Mapped[Date] = mapped_column(Date, nullable=False)
  quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
  job_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  section_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
  created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
