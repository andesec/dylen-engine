from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user, require_feature_flag, require_permission, require_tier
from app.schema.fenster import FensterWidget, FensterWidgetType
from app.schema.lessons import Lesson, Section, Subsection, SubsectionWidget
from app.schema.sql import User

router = APIRouter()


def _render_fenster_widget_response(widget: FensterWidget) -> Response:
  """Render the fenster widget based on persisted storage type."""
  if widget.type == FensterWidgetType.INLINE_BLOB:
    if not widget.content:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget content missing")
    return Response(content=widget.content, media_type="text/html; charset=utf-8", headers={"Content-Encoding": "br", "Content-Security-Policy": "frame-ancestors 'self'"})
  if widget.type == FensterWidgetType.CDN_URL:
    if not widget.url:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget URL missing")
    return RedirectResponse(url=widget.url, status_code=status.HTTP_302_FOUND)
  raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unsupported widget type: {widget.type}")


@router.get("/{widget_id}", dependencies=[Depends(require_permission("fenster:view")), Depends(require_tier(["Plus", "Pro"])), Depends(require_feature_flag("feature.fenster"))])
async def get_fenster_widget(widget_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user)) -> Response:
  """
  Retrieve a Fenster widget by ID.
  Requires 'Plus' or 'Pro' tier.
  """
  widget: FensterWidget | None = None
  try:
    fenster_uuid = uuid.UUID(widget_id)
  except ValueError:
    fenster_uuid = None

  # Legacy path compatibility:
  # 1) Try direct fenster UUID lookup first.
  # 2) If not a UUID / not found, treat the same path param as subsection_widget public_id.
  if fenster_uuid is not None:
    stmt = select(FensterWidget).where(FensterWidget.fenster_id == fenster_uuid, FensterWidget.creator_id == str(current_user.id), FensterWidget.is_archived.is_(False), FensterWidget.status == "completed")
    result = await db.execute(stmt)
    widget = result.scalar_one_or_none()
  if widget is None:
    stmt = select(FensterWidget).where(FensterWidget.public_id == widget_id, FensterWidget.creator_id == str(current_user.id), FensterWidget.is_archived.is_(False), FensterWidget.status == "completed")
    result = await db.execute(stmt)
    widget = result.scalar_one_or_none()
  if widget is None:
    mapping_stmt = (
      select(SubsectionWidget.widget_id)
      .join(Subsection, Subsection.id == SubsectionWidget.subsection_id)
      .join(Section, Section.section_id == Subsection.section_id)
      .join(Lesson, Lesson.lesson_id == Section.lesson_id)
      .where(SubsectionWidget.public_id == widget_id, SubsectionWidget.widget_type == "fenster", SubsectionWidget.is_archived.is_(False), Subsection.is_archived.is_(False), Lesson.user_id == str(current_user.id), Lesson.is_archived.is_(False))
      .limit(1)
    )
    mapping_result = await db.execute(mapping_stmt)
    mapping = mapping_result.first()
    if mapping is None or mapping.widget_id is None:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")
    mapped_widget_id = str(mapping.widget_id).strip()
    fenster_stmt = select(FensterWidget).where(FensterWidget.public_id == mapped_widget_id, FensterWidget.creator_id == str(current_user.id), FensterWidget.is_archived.is_(False), FensterWidget.status == "completed")
    fenster_result = await db.execute(fenster_stmt)
    widget = fenster_result.scalar_one_or_none()
    if widget is None:
      try:
        mapped_uuid = uuid.UUID(mapped_widget_id)
      except ValueError:
        mapped_uuid = None
      if mapped_uuid is not None:
        legacy_stmt = select(FensterWidget).where(FensterWidget.fenster_id == mapped_uuid, FensterWidget.creator_id == str(current_user.id), FensterWidget.is_archived.is_(False), FensterWidget.status == "completed")
        widget = (await db.execute(legacy_stmt)).scalar_one_or_none()
  if widget is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")
  return _render_fenster_widget_response(widget)


@router.get("/subsection-widget/{subsection_widget_id}", dependencies=[Depends(require_permission("fenster:view")), Depends(require_tier(["Plus", "Pro"])), Depends(require_feature_flag("feature.fenster"))])
async def get_fenster_widget_by_subsection_widget_id(subsection_widget_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_active_user)) -> Response:
  """Retrieve a fenster widget using the subsection_widget public id."""
  mapping_stmt = (
    select(SubsectionWidget.widget_type, SubsectionWidget.widget_id)
    .join(Subsection, Subsection.id == SubsectionWidget.subsection_id)
    .join(Section, Section.section_id == Subsection.section_id)
    .join(Lesson, Lesson.lesson_id == Section.lesson_id)
    .where(SubsectionWidget.public_id == subsection_widget_id, SubsectionWidget.widget_type == "fenster", SubsectionWidget.is_archived.is_(False), Subsection.is_archived.is_(False), Lesson.user_id == str(current_user.id), Lesson.is_archived.is_(False))
    .limit(1)
  )
  mapping_result = await db.execute(mapping_stmt)
  mapping = mapping_result.first()
  if mapping is None or mapping.widget_id is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")
  mapped_widget_id = str(mapping.widget_id).strip()

  fenster_stmt = select(FensterWidget).where(FensterWidget.public_id == mapped_widget_id, FensterWidget.creator_id == str(current_user.id), FensterWidget.is_archived.is_(False), FensterWidget.status == "completed")
  fenster_result = await db.execute(fenster_stmt)
  widget = fenster_result.scalar_one_or_none()
  if widget is None:
    try:
      mapped_uuid = uuid.UUID(mapped_widget_id)
    except ValueError:
      mapped_uuid = None
    if mapped_uuid is not None:
      legacy_stmt = select(FensterWidget).where(FensterWidget.fenster_id == mapped_uuid, FensterWidget.creator_id == str(current_user.id), FensterWidget.is_archived.is_(False), FensterWidget.status == "completed")
      widget = (await db.execute(legacy_stmt)).scalar_one_or_none()
  if widget is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")
  return _render_fenster_widget_response(widget)
