from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user, require_permission
from app.schema.illustrations import Illustration
from app.schema.lessons import Lesson, Section, Subsection, SubsectionWidget
from app.schema.sql import User
from app.services.storage_client import build_storage_client

router = APIRouter()
_IMAGE_NAME_RE = re.compile(r"^[0-9]+\.webp$")


def _candidate_media_identifiers(image_name: str) -> tuple[str, str | None]:
  """Return normalized lookup candidates for media identifiers."""
  normalized = str(image_name).strip()
  if normalized.lower().endswith(".webp") and len(normalized) > 5:
    return normalized, normalized[:-5]
  return normalized, None


@router.get("/lessons/{lesson_id}/{image_name}", dependencies=[Depends(require_permission("media:view_own"))])
async def get_lesson_media(lesson_id: str, image_name: str, db_session: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user), settings: Settings = Depends(get_settings)) -> Response:  # noqa: B008
  """Authorize lesson media access and stream illustration bytes through the backend."""
  user_id = str(current_user.id)
  illustration: Illustration | None = None
  raw_identifier, base_identifier = _candidate_media_identifiers(image_name)

  # Legacy path compatibility:
  # 1) Old flow uses storage object names like `123.webp`.
  # 2) New widget flow can pass subsection_widget public_id in the same path slot.
  if _IMAGE_NAME_RE.match(raw_identifier):
    stmt = (
      select(Illustration)
      .join(Section, Section.illustration_id == Illustration.id)
      .join(Lesson, Lesson.lesson_id == Section.lesson_id)
      .where(Lesson.lesson_id == lesson_id, Lesson.user_id == user_id, Illustration.storage_object_name == raw_identifier, Illustration.status == "completed", Illustration.is_archived.is_(False))
      .limit(1)
    )
    result = await db_session.execute(stmt)
    illustration = result.scalar_one_or_none()
  else:
    public_id_candidates = [raw_identifier]
    if base_identifier:
      public_id_candidates.append(base_identifier)
    direct_resource_stmt = (
      select(Illustration)
      .join(Section, Section.illustration_id == Illustration.id)
      .join(Lesson, Lesson.lesson_id == Section.lesson_id)
      .where(
        Lesson.lesson_id == lesson_id,
        Lesson.user_id == user_id,
        Lesson.is_archived.is_(False),
        Illustration.status == "completed",
        Illustration.is_archived.is_(False),
        (Illustration.public_id.in_(public_id_candidates)) | (Illustration.storage_object_name == raw_identifier),
      )
      .limit(1)
    )
    direct_resource_result = await db_session.execute(direct_resource_stmt)
    illustration = direct_resource_result.scalar_one_or_none()
  if illustration is None and not _IMAGE_NAME_RE.match(raw_identifier):
    widget_public_id = base_identifier or raw_identifier
    mapping_stmt = (
      select(SubsectionWidget.widget_id)
      .join(Subsection, Subsection.id == SubsectionWidget.subsection_id)
      .join(Section, Section.section_id == Subsection.section_id)
      .join(Lesson, Lesson.lesson_id == Section.lesson_id)
      .where(
        Lesson.lesson_id == lesson_id,
        Lesson.user_id == user_id,
        Lesson.is_archived.is_(False),
        SubsectionWidget.public_id == widget_public_id,
        SubsectionWidget.widget_type == "illustration",
        SubsectionWidget.is_archived.is_(False),
        Subsection.is_archived.is_(False),
      )
      .limit(1)
    )
    mapping_result = await db_session.execute(mapping_stmt)
    mapping = mapping_result.first()
    if mapping is not None and mapping.widget_id is not None:
      mapped_resource_id = str(mapping.widget_id).strip()
      if mapped_resource_id:
        illustration_stmt = select(Illustration).where(Illustration.public_id == mapped_resource_id, Illustration.status == "completed", Illustration.is_archived.is_(False)).limit(1)
        illustration_result = await db_session.execute(illustration_stmt)
        illustration = illustration_result.scalar_one_or_none()
        if illustration is None:
          try:
            mapped_legacy_id = int(mapped_resource_id)
          except ValueError:
            mapped_legacy_id = None
          if mapped_legacy_id is not None:
            legacy_stmt = select(Illustration).where(Illustration.id == mapped_legacy_id, Illustration.status == "completed", Illustration.is_archived.is_(False)).limit(1)
            legacy_result = await db_session.execute(legacy_stmt)
            illustration = legacy_result.scalar_one_or_none()

  if illustration is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

  storage_client = build_storage_client(settings)
  try:
    image_bytes, _metadata = await storage_client.download(illustration.storage_object_name)
  except Exception:  # noqa: BLE001
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found") from None

  return Response(content=image_bytes, media_type="image/webp", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/widgets/{subsection_widget_id}/illustration", dependencies=[Depends(require_permission("media:view_own"))])
async def get_widget_illustration(
  subsection_widget_id: str,
  db_session: AsyncSession = Depends(get_db),
  current_user: User = Depends(get_current_active_user),
  settings: Settings = Depends(get_settings),  # noqa: B008
) -> Response:
  """Authorize widget-linked illustration access using subsection widget public ids."""
  mapping_stmt = (
    select(SubsectionWidget.widget_id)
    .join(Subsection, Subsection.id == SubsectionWidget.subsection_id)
    .join(Section, Section.section_id == Subsection.section_id)
    .join(Lesson, Lesson.lesson_id == Section.lesson_id)
    .where(
      SubsectionWidget.public_id == subsection_widget_id, SubsectionWidget.widget_type == "illustration", SubsectionWidget.is_archived.is_(False), Subsection.is_archived.is_(False), Lesson.user_id == str(current_user.id), Lesson.is_archived.is_(False)
    )
    .limit(1)
  )
  mapping_result = await db_session.execute(mapping_stmt)
  mapping = mapping_result.first()
  if mapping is None or mapping.widget_id is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
  mapped_widget_id = str(mapping.widget_id).strip()
  illustration_stmt = select(Illustration).where(Illustration.public_id == mapped_widget_id, Illustration.status == "completed", Illustration.is_archived.is_(False)).limit(1)
  illustration_result = await db_session.execute(illustration_stmt)
  illustration = illustration_result.scalar_one_or_none()
  if illustration is None:
    try:
      mapped_legacy_id = int(mapped_widget_id)
    except ValueError:
      mapped_legacy_id = None
    if mapped_legacy_id is not None:
      legacy_stmt = select(Illustration).where(Illustration.id == mapped_legacy_id, Illustration.status == "completed", Illustration.is_archived.is_(False)).limit(1)
      legacy_result = await db_session.execute(legacy_stmt)
      illustration = legacy_result.scalar_one_or_none()
  if illustration is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

  storage_client = build_storage_client(settings)
  try:
    image_bytes, _metadata = await storage_client.download(illustration.storage_object_name)
  except Exception:  # noqa: BLE001
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found") from None

  return Response(content=image_bytes, media_type="image/webp", headers={"Cache-Control": "public, max-age=3600"})
