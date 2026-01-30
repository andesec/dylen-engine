"""SQLAlchemy models for subscription tiers and per-user quota tracking."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SubscriptionTier(Base):
  __tablename__ = "subscription_tiers"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
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
  concurrent_coach_limit: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1, server_default="1")
  coach_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
  coach_voice_tier: Mapped[str | None] = mapped_column(String, nullable=True)


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
  concurrent_coach_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
  coach_mode_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


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
