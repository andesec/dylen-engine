from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user, require_permission
from app.schema.sql import User
from app.schema.tutor import TutorAudio

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/job/{job_id}/audios", dependencies=[Depends(require_permission("tutor:audio_view_own"))])
async def get_job_audios(job_id: str, request: Request, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user)) -> dict[str, Any]:
  """Retrieve list of generated audios for a job."""
  stmt = select(TutorAudio).where(TutorAudio.job_id == job_id).order_by(TutorAudio.section_number, TutorAudio.subsection_index)
  result = await db_session.execute(stmt)
  audios = result.scalars().all()

  return {
    "job_id": job_id,
    "audios": [
      {
        "id": audio.id,
        "section_number": audio.section_number,
        "subsection_index": audio.subsection_index,
        "text_content": audio.text_content,
        # Avoid hardcoded paths so refactors don't break API clients.
        "audio_url": str(request.url_for("get_audio_content", audio_id=audio.id)),
      }
      for audio in audios
    ],
  }


@router.get("/audio/{audio_id}/content", dependencies=[Depends(require_permission("tutor:audio_view_own"))])
async def get_audio_content(audio_id: int, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user)) -> Response:
  """Stream audio content."""
  stmt = select(TutorAudio).where(TutorAudio.id == audio_id)
  result = await db_session.execute(stmt)
  audio = result.scalar_one_or_none()

  if not audio:
    raise HTTPException(status_code=404, detail="Audio not found")

  return Response(content=audio.audio_data, media_type="audio/mpeg")
