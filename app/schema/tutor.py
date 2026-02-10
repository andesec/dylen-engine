"""SQLAlchemy model for storing generated tutor audio."""

from __future__ import annotations

import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TutorAudio(Base):
  """Persist generated audio blobs alongside their source text."""

  __tablename__ = "tutor_audios"

  id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
  job_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
  section_number: Mapped[int] = mapped_column(Integer, nullable=False)
  subsection_index: Mapped[int] = mapped_column(Integer, nullable=False)
  text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
  audio_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
  created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
