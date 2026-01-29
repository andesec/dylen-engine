from sqlalchemy import Column, DateTime, Integer, LargeBinary, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class CoachAudio(Base):
  __tablename__ = "coach_audios"

  id = Column(Integer, primary_key=True, index=True)
  job_id = Column(String, index=True, nullable=False)
  section_number = Column(Integer, nullable=False)
  subsection_index = Column(Integer, nullable=False)
  text_content = Column(Text, nullable=True)
  audio_data = Column(LargeBinary, nullable=False)
  created_at = Column(DateTime(timezone=True), server_default=func.now())
