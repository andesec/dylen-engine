from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.security import get_current_user
from app.notifications.template_renderer import render_push_content
from app.schema.email_delivery_logs import EmailDeliveryLog
from app.schema.sql import User

router = APIRouter()


@router.get("/", response_model=list[dict[str, Any]])
async def list_notifications(
  current_user: User = Depends(get_current_user),  # noqa: B008
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
  # Build the query
  query = select(EmailDeliveryLog).where(EmailDeliveryLog.user_id == current_user.id)

  if created_after:
    query = query.where(EmailDeliveryLog.created_at > created_after)

  # Apply ordering and pagination
  query = query.order_by(desc(EmailDeliveryLog.created_at)).limit(limit).offset(offset)

  result = await session.execute(query)
  logs = result.scalars().all()

  notifications = []
  for log in logs:
    try:
      # Render the push-style content for the frontend
      title, body, data = render_push_content(template_id=log.template_id, placeholders=log.placeholders)

      notifications.append(
        {
          "id": str(log.id),
          "created_at": log.created_at,
          "template_id": log.template_id,
          "title": title,
          "body": body,
          "data": data,
          "read": False,  # TODO: Implement read status tracking
        }
      )
    except ValueError:
      # Skip notifications with unknown templates or missing data
      continue

  return notifications
