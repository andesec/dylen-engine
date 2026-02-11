"""SQLAlchemy model for storing generated tutor records."""

from __future__ import annotations

import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tutor(Base):
  """Persist generated audio blobs alongside their source text."""

  __tablename__ = "tutors"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
  creator_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
  job_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
  section_number: Mapped[int] = mapped_column(Integer, nullable=False)
  subsection_index: Mapped[int] = mapped_column(Integer, nullable=False)
  text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
  audio_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
  status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
  is_archived: Mapped[bool] = mapped_column(nullable=False, default=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
  updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
