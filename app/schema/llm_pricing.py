"""SQLAlchemy models for LLM pricing configuration."""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LlmModelPricing(Base):
  """Global pricing metadata for LLM models."""

  __tablename__ = "llm_model_pricing"
  # Enforce unique pricing rows per provider/model.
  __table_args__ = (UniqueConstraint("provider", "model", name="ux_llm_model_pricing_provider_model"),)

  id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
  model: Mapped[str] = mapped_column(String, nullable=False, index=True)
  input_per_1m: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
  output_per_1m: Mapped[float] = mapped_column(Numeric(12, 6), nullable=False)
  is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
