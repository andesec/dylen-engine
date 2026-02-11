"""Repository for tutor audio data access using PostgreSQL."""

from __future__ import annotations

import msgspec
from sqlalchemy import String, cast, func, select

from app.core.database import get_session_factory
from app.schema.jobs import Job
from app.schema.sql import User
from app.schema.tutor import TutorAudio


class TutorAudioRecord(msgspec.Struct):
  """Tutor audio record for API responses."""

  id: int
  job_id: str
  section_number: int
  subsection_index: int
  text_content: str | None
  audio_size_bytes: int  # Size of audio data
  created_at: str
  lesson_id: str | None  # From job
  user_email: str | None  # From job -> user


class PostgresTutorAudioRepository:
  """Persist and retrieve tutor audios from Postgres using SQLAlchemy."""

  def __init__(self, table_name: str = "tutor_audios") -> None:
    self._session_factory = get_session_factory()
    if self._session_factory is None:
      raise RuntimeError("Database not initialized")

  async def list_tutor_audios(self, page: int = 1, limit: int = 20, job_id: str | None = None, section_number: int | None = None, sort_by: str = "created_at", sort_order: str = "desc") -> tuple[list[TutorAudioRecord], int]:
    """Return a paginated list of tutor audios with filters, sorting, and total count."""
    async with self._session_factory() as session:
      # Calculate offset from page
      offset = (page - 1) * limit

      # Build base query with joins for enriched data
      stmt = (
        select(TutorAudio, Job.lesson_id, User.email)
        .outerjoin(Job, Job.job_id == TutorAudio.job_id)
        # jobs.user_id is stored as varchar, so cast users.id for a type-safe join.
        .outerjoin(User, cast(User.id, String) == Job.user_id)
        .limit(limit)
        .offset(offset)
      )

      count_stmt = select(func.count()).select_from(TutorAudio)

      # Apply filters
      conditions = []
      if job_id:
        conditions.append(TutorAudio.job_id == job_id)
      if section_number is not None:
        conditions.append(TutorAudio.section_number == section_number)

      if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

      # Apply sorting
      sort_column = TutorAudio.created_at  # default
      if sort_by == "id":
        sort_column = TutorAudio.id
      elif sort_by == "created_at":
        sort_column = TutorAudio.created_at
      elif sort_by == "job_id":
        sort_column = TutorAudio.job_id
      elif sort_by == "section_number":
        sort_column = TutorAudio.section_number

      if sort_order.lower() == "asc":
        stmt = stmt.order_by(sort_column.asc())
      else:
        stmt = stmt.order_by(sort_column.desc())

      # Execute queries
      total = await session.scalar(count_stmt)
      result = await session.execute(stmt)
      rows = result.all()

      records = []
      for row in rows:
        audio, lesson_id, user_email = row
        records.append(
          TutorAudioRecord(
            id=audio.id,
            job_id=audio.job_id,
            section_number=audio.section_number,
            subsection_index=audio.subsection_index,
            text_content=audio.text_content,
            audio_size_bytes=len(audio.audio_data) if audio.audio_data else 0,
            created_at=audio.created_at.isoformat(),
            lesson_id=lesson_id,
            user_email=user_email,
          )
        )

      return records, (total or 0)
