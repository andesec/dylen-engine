from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class Illustration(Base):
  """Persist generated illustration metadata and object storage coordinates."""

  __tablename__ = "illustrations"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
  public_id: Mapped[str] = mapped_column(String, nullable=False, index=True, unique=True)
  creator_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
  storage_bucket: Mapped[str] = mapped_column(Text, nullable=False)
  storage_object_name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
  mime_type: Mapped[str] = mapped_column(String, nullable=False)
  caption: Mapped[str] = mapped_column(Text, nullable=False)
  ai_prompt: Mapped[str] = mapped_column(Text, nullable=False)
  keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
  status: Mapped[str] = mapped_column(String, nullable=False)
  is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
  regenerate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
  updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
