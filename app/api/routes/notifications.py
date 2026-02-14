from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.security import get_current_active_user, require_permission
from app.schema.notifications import InAppNotification
from app.schema.sql import User

router = APIRouter()


@router.get("/", response_model=list[dict[str, Any]], dependencies=[Depends(require_permission("notification:list_own"))])
async def list_notifications(
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  session: AsyncSession = Depends(get_db_session),  # noqa: B008
  limit: int = Query(20, ge=1, le=100),  # noqa: B008
  offset: int = Query(0, ge=0),  # noqa: B008
  created_after: datetime | None = Query(None),  # noqa: B008
) -> list[dict[str, Any]]:
  """
  Poll for recent notifications for the current user.

  Returns a list of notifications derived from email delivery logs,
  formatted for frontend display with navigation data.

  - **limit**: Max number of notifications to return.
  - **offset**: Number of notifications to skip (for pagination).
  - **created_after**: Only return notifications created after this timestamp (useful for polling).
  """
  # Build the query for in-app notifications.
  query = select(InAppNotification).where(InAppNotification.user_id == current_user.id)

  if created_after:
    query = query.where(InAppNotification.created_at > created_after)

  # Apply ordering and pagination.
  query = query.order_by(desc(InAppNotification.created_at)).limit(limit).offset(offset)

  result = await session.execute(query)
  notifications = result.scalars().all()

  # Map persisted rows into API payloads.
  payloads = []
  for notification in notifications:
    payloads.append({"id": str(notification.id), "created_at": notification.created_at, "template_id": notification.template_id, "title": notification.title, "body": notification.body, "data": notification.data_json, "read": bool(notification.read)})

  return payloads
