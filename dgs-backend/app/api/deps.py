"""Shared FastAPI dependencies for auth and quota enforcement."""

from __future__ import annotations

import logging
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.config import get_settings
from app.core.security import get_current_active_user
from app.schema.sql import User
from app.services.quotas import QuotaExceededError, ResolvedQuota, consume_quota, resolve_quota

logger = logging.getLogger(__name__)


async def get_quota(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> ResolvedQuota:  # noqa: B008
  """Resolve the current user's effective quota limits."""
  try:
    return await resolve_quota(db, current_user.id)
  except Exception as exc:
    logger.error("Failed to resolve quota for user %s: %s", current_user.id, exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to resolve quota") from exc


async def consume_section_quota(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> None:  # noqa: B008
  """Consume one generated-section quota before processing."""
  try:
    await consume_quota(db, user_id=uuid.UUID(str(current_user.id)), action="SECTION_GEN", quantity=1)
  except QuotaExceededError:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="QUOTA_EXCEEDED") from None
  except Exception as exc:  # pragma: no cover - safety net
    logger.error("Failed to consume section quota for user %s: %s", current_user.id, exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to consume quota") from exc


async def require_dev_key(x_dev_key: str = Header(default=""), settings=Depends(get_settings)) -> None:  # noqa: B008
  """Authorize requests using the pre-shared developer key."""
  # Compare provided header to configured key to gate dev-only routes.
  if not settings.dev_key or x_dev_key != settings.dev_key:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid developer key")
