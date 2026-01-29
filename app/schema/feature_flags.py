"""SQLAlchemy models for DB-backed feature flags (per tier + per organization)."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FeatureFlag(Base):
  """Feature flag definition with a safe default."""

  __tablename__ = "feature_flags"

  id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
  description: Mapped[str | None] = mapped_column(Text, nullable=True)
  default_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrganizationFeatureFlag(Base):
  """Organization-level overrides for feature flags."""

  __tablename__ = "organization_feature_flags"

  org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
  feature_flag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feature_flags.id"), primary_key=True)
  enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SubscriptionTierFeatureFlag(Base):
  """Subscription-tier defaults for feature flags."""

  __tablename__ = "subscription_tier_feature_flags"

  subscription_tier_id: Mapped[int] = mapped_column(ForeignKey("subscription_tiers.id"), primary_key=True)
  feature_flag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feature_flags.id"), primary_key=True)
  enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
