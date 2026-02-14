"""Shared FastAPI dependencies for auth and quota enforcement."""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_active_user
from app.schema.sql import User
from app.services.quotas import ResolvedQuota, resolve_quota

logger = logging.getLogger(__name__)


async def get_db_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:  # noqa: B008
  """Dependency to get the database session."""
  return session


async def get_quota(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> ResolvedQuota:  # noqa: B008
  """Resolve the current user's effective quota limits."""
  try:
    return await resolve_quota(db, current_user.id)
  except Exception as exc:
    logger.error("Failed to resolve quota for user %s: %s", current_user.id, exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to resolve quota") from exc
