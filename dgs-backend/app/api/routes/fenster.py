from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_tier
from app.schema.fenster import FensterWidget, FensterWidgetType

router = APIRouter()


@router.get("/{widget_id}", dependencies=[Depends(require_tier(["Plus", "Pro"]))])
async def get_fenster_widget(widget_id: str, db: AsyncSession = Depends(get_db)) -> Response:
  """
  Retrieve a Fenster widget by ID.
  Requires 'Plus' or 'Pro' tier.
  """
  try:
    fenster_uuid = uuid.UUID(widget_id)
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid widget ID") from exc

  stmt = select(FensterWidget).where(FensterWidget.fenster_id == fenster_uuid)
  result = await db.execute(stmt)
  widget = result.scalar_one_or_none()

  if not widget:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget not found")

  if widget.type == FensterWidgetType.INLINE_BLOB:
    if not widget.content:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget content missing")

    return Response(content=widget.content, media_type="text/html; charset=utf-8", headers={"Content-Encoding": "br", "Content-Security-Policy": "frame-ancestors 'self'"})
  elif widget.type == FensterWidgetType.CDN_URL:
    if not widget.url:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Widget URL missing")
    return RedirectResponse(url=widget.url, status_code=status.HTTP_302_FOUND)

  raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Unsupported widget type: {widget.type}")
