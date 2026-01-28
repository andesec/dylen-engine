from __future__ import annotations

import base64
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_tier
from app.schema.fenster import FensterWidget, FensterWidgetType

router = APIRouter()


@router.get("/{widget_id}", dependencies=[Depends(require_tier(["Plus", "Pro"]))])
async def get_fenster_widget(widget_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
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

  response = {
    "fenster_id": str(widget.fenster_id),
    "type": widget.type.value,
    "content": None,
    "url": widget.url,
  }

  if widget.type == FensterWidgetType.INLINE_BLOB and widget.content:
    # Encode binary brotli content to base64 string
    response["content"] = base64.b64encode(widget.content).decode("utf-8")

  return response
