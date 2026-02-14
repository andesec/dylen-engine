"""Maintenance services for scheduled background cleanup tasks."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from app.config import Settings
from app.schema.lessons import Lesson
from app.schema.quotas import UserUsageMetrics
from app.schema.sql import User
from app.services.runtime_config import resolve_effective_runtime_config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def archive_old_lessons(session: AsyncSession, *, settings: Settings) -> int:
  """Archive older lessons beyond the per-tier history keep limit.

  How/Why:
    - Lessons are retained in the database for internal audit and support workflows.
    - End users should only access the most recent N lessons per tier, enforced by `is_archived`.
    - This job is intended to be executed via Cloud Tasks on a schedule (e.g., daily 1am UTC) and on-demand via an admin trigger.
  """
  archived_total = 0
  # Iterate over users that have a tier/usage row so tier resolution stays consistent.
  stmt = select(UserUsageMetrics.user_id, UserUsageMetrics.subscription_tier_id, User.org_id).join(User, User.id == UserUsageMetrics.user_id)
  result = await session.execute(stmt)
  rows = result.fetchall()
  for user_id, subscription_tier_id, org_id in rows:
    # Resolve tier-scoped history limits for each user so upgrades/downgrades are applied dynamically.
    runtime_config = await resolve_effective_runtime_config(session, settings=settings, org_id=org_id, subscription_tier_id=int(subscription_tier_id), user_id=None)
    keep = int(runtime_config.get("limits.history_lessons_kept") or 0)
    if keep <= 0:
      continue
    # Lessons store user_id as string; normalize to the same representation used at write time.
    lesson_user_id = str(uuid.UUID(str(user_id)))
    # Select lessons beyond the newest N that are still available.
    candidates_stmt = select(Lesson.lesson_id).where(Lesson.user_id == lesson_user_id, Lesson.is_archived == sa.false()).order_by(Lesson.created_at.desc()).offset(keep)  # type: ignore[name-defined]
    candidates_result = await session.execute(candidates_stmt)
    lesson_ids = [str(row[0]) for row in candidates_result.fetchall()]
    if not lesson_ids:
      continue
    # Archive in bulk so the job remains efficient even for large histories.
    await session.execute(sa.update(Lesson).where(Lesson.lesson_id.in_(lesson_ids)).values(is_archived=True))  # type: ignore[name-defined]
    archived_total += len(lesson_ids)
  await session.commit()
  return archived_total
