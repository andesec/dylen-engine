from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class Illustration(Base):
  """Persist generated illustration metadata and object storage coordinates."""

  __tablename__ = "illustrations"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
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

  sections: Mapped[list[SectionIllustration]] = relationship("SectionIllustration", back_populates="illustration", cascade="all, delete-orphan")


class SectionIllustration(Base):
  """Join rows linking sections to illustration assets."""

  __tablename__ = "section_illustrations"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
  section_id: Mapped[int] = mapped_column(Integer, ForeignKey("sections.section_id", ondelete="CASCADE"), nullable=False, index=True)
  illustration_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("illustrations.id", ondelete="CASCADE"), nullable=False, index=True)
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

  illustration: Mapped[Illustration] = relationship("Illustration", back_populates="sections")
