"""User CRUD helpers implemented with SQLAlchemy ORM.

This module centralizes how and why user records are created/updated so transport
layers (routes, auth dependencies, workers) don't duplicate query logic.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schema.sql import User
from app.schema.quotas import SubscriptionTier, UserUsageMetrics

logger = logging.getLogger(__name__)


# ... (rest of imports are fine)


async def ensure_usage_row(session: AsyncSession, user: User, *, tier_id: int | None = None) -> UserUsageMetrics:
  """Ensure a usage metrics row exists for the user."""
  # Avoid duplicate rows by checking first.
  stmt = select(UserUsageMetrics).where(UserUsageMetrics.user_id == user.id)
  result = await session.execute(stmt)
  existing = result.scalar_one_or_none()
  if existing:
    return existing

  # Default to provided tier or 'Free' tier if not specified.
  if tier_id is None:
      tier_stmt = select(SubscriptionTier).where(SubscriptionTier.name == "Free")
      tier_result = await session.execute(tier_stmt)
      free_tier = tier_result.scalar_one_or_none()
      if not free_tier:
          # Critical configuration error: 'Free' tier must exist.
          raise RuntimeError("Default 'Free' subscription tier not found in database. Seed data missing?")
      tier_id = free_tier.id

  metrics = UserUsageMetrics(user_id=user.id, subscription_tier_id=tier_id, files_uploaded_count=0, images_uploaded_count=0, sections_generated_count=0)
  session.add(metrics)
  await session.commit()
  await session.refresh(metrics)
  return metrics
