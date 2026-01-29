"""SQLAlchemy models for runtime configuration values stored in Postgres."""

from __future__ import annotations

import datetime
import uuid
from enum import Enum
from typing import Any

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RuntimeConfigScope(str, Enum):
  """Supported configuration scopes for runtime overrides."""

  GLOBAL = "GLOBAL"
  TIER = "TIER"
  TENANT = "TENANT"


class RuntimeConfigValue(Base):
  """A typed runtime config value stored as JSON with a scope discriminator."""

  __tablename__ = "runtime_config_values"
  __table_args__ = (
    Index("ux_runtime_config_values_global", "key", unique=True, postgresql_where=sa.text("scope = 'GLOBAL'")),
    Index("ux_runtime_config_values_tenant", "key", "org_id", unique=True, postgresql_where=sa.text("scope = 'TENANT'")),
    Index("ux_runtime_config_values_tier", "key", "subscription_tier_id", unique=True, postgresql_where=sa.text("scope = 'TIER'")),
  )

  id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
  key: Mapped[str] = mapped_column(String, nullable=False, index=True)
  scope: Mapped[RuntimeConfigScope] = mapped_column(SAEnum(RuntimeConfigScope, name="runtime_config_scope"), nullable=False, index=True)
  org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
  subscription_tier_id: Mapped[int | None] = mapped_column(ForeignKey("subscription_tiers.id"), nullable=True, index=True)
  value_json: Mapped[dict[str, Any] | list[Any] | str | int | float | bool | None] = mapped_column(JSONB, nullable=False)
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
