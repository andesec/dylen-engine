from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user, require_permission
from app.schema.illustrations import Illustration, SectionIllustration
from app.schema.lessons import Lesson, Section
from app.schema.sql import User
from app.services.storage_client import build_storage_client

router = APIRouter()
_IMAGE_NAME_RE = re.compile(r"^[0-9]+\.webp$")


@router.get("/lessons/{lesson_id}/{image_name}", dependencies=[Depends(require_permission("media:view_own"))])
async def get_lesson_media(lesson_id: str, image_name: str, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user), settings: Settings = Depends(get_settings)) -> Response:  # noqa: B008
  """Authorize lesson media access and stream illustration bytes through the backend."""
  # Keep object name resolution strict to avoid path tricks and noisy DB scans.
  if not _IMAGE_NAME_RE.match(image_name):
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
  user_id = str(current_user.id)
  stmt = (
    select(Illustration)
    .join(SectionIllustration, SectionIllustration.illustration_id == Illustration.id)
    .join(Section, Section.section_id == SectionIllustration.section_id)
    .join(Lesson, Lesson.lesson_id == Section.lesson_id)
    .where(Lesson.lesson_id == lesson_id, Lesson.user_id == user_id, Illustration.storage_object_name == image_name, Illustration.status == "completed", Illustration.is_archived.is_(False))
    .limit(1)
  )
  result = await db_session.execute(stmt)
  illustration = result.scalar_one_or_none()
  if illustration is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

  storage_client = build_storage_client(settings)
  try:
    image_bytes, _metadata = await storage_client.download(illustration.storage_object_name)
  except Exception:  # noqa: BLE001
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found") from None

  return Response(content=image_bytes, media_type="image/webp", headers={"Cache-Control": "public, max-age=3600"})
