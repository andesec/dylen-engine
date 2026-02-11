from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user, require_permission
from app.schema.sql import User
from app.schema.tutor import Tutor

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/job/{job_id}/tutors", dependencies=[Depends(require_permission("tutor:audio_view_own"))])
async def get_job_tutors(job_id: str, request: Request, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user)) -> dict[str, Any]:
  """Retrieve list of generated tutor records for a job."""
  stmt = select(Tutor).where(Tutor.job_id == job_id, Tutor.creator_id == str(current_user.id), Tutor.is_archived.is_(False)).order_by(Tutor.section_number, Tutor.subsection_index)
  result = await db_session.execute(stmt)
  tutors = result.scalars().all()

  return {
    "job_id": job_id,
    "tutors": [
      {
        "id": tutor.id,
        "section_number": tutor.section_number,
        "subsection_index": tutor.subsection_index,
        "text_content": tutor.text_content,
        # Avoid hardcoded paths so refactors don't break API clients.
        "audio_url": str(request.url_for("get_tutor_content", tutor_id=tutor.id)),
      }
      for tutor in tutors
    ],
  }


@router.get("/{tutor_id}/content", dependencies=[Depends(require_permission("tutor:audio_view_own"))])
async def get_tutor_content(tutor_id: int, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user)) -> Response:
  """Stream tutor audio content."""
  stmt = select(Tutor).where(Tutor.id == tutor_id, Tutor.creator_id == str(current_user.id), Tutor.is_archived.is_(False))
  result = await db_session.execute(stmt)
  tutor = result.scalar_one_or_none()

  if not tutor:
    raise HTTPException(status_code=404, detail="Tutor not found")

  return Response(content=tutor.audio_data, media_type="audio/mpeg")
