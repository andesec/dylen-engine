"""Quota bucket services for period-based enforcement and logging."""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from app.schema.quotas import QuotaPeriod, UserQuotaBucket, UserUsageLog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class QuotaExceededError(RuntimeError):
  """Raised when a quota bucket would exceed its configured limit."""


@dataclass(frozen=True)
class QuotaSnapshot:
  """Snapshot of a single quota metric for the active period."""

  metric_key: str
  period: QuotaPeriod
  period_start: datetime.date
  limit: int
  used: int
  remaining: int


def _utc_now() -> datetime.datetime:
  """Return timezone-aware current UTC time for deterministic period math."""
  return datetime.datetime.now(datetime.UTC)


def period_start_date(*, now: datetime.datetime, period: QuotaPeriod) -> datetime.date:
  """Compute the period start date for the given UTC timestamp."""
  # Use UTC boundaries so quotas are consistent across regions.
  if now.tzinfo is None:
    raise ValueError("now must be timezone-aware (UTC).")
  if period == QuotaPeriod.WEEK:
    # Week starts Monday 00:00 UTC.
    monday = now.date() - datetime.timedelta(days=now.date().weekday())
    return monday
  if period == QuotaPeriod.MONTH:
    # Month starts on the 1st 00:00 UTC.
    return now.date().replace(day=1)
  raise ValueError(f"Unsupported period: {period}")


async def get_quota_snapshot(session: AsyncSession, *, user_id: uuid.UUID, metric_key: str, period: QuotaPeriod, limit: int) -> QuotaSnapshot:
  """Return current used/remaining for the active period for a metric."""
  # Normalize limits so callers can treat zero as disabled.
  normalized_limit = int(limit)
  if normalized_limit < 0:
    raise ValueError("limit must be >= 0")

  now = _utc_now()
  start = period_start_date(now=now, period=period)
  stmt = select(UserQuotaBucket.used).where(UserQuotaBucket.user_id == user_id, UserQuotaBucket.metric_key == metric_key, UserQuotaBucket.period == period, UserQuotaBucket.period_start == start)
  result = await session.execute(stmt)
  used = int(result.scalar_one_or_none() or 0)
  remaining = max(normalized_limit - used, 0)
  return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=used, remaining=remaining)


async def consume_quota(session: AsyncSession, *, user_id: uuid.UUID, metric_key: str, period: QuotaPeriod, quantity: int, limit: int, metadata: dict | None = None) -> QuotaSnapshot:
  """Atomically consume quota for a metric and append a usage log entry."""
  if quantity <= 0:
    raise ValueError("quantity must be positive.")
  normalized_limit = int(limit)
  if normalized_limit < 0:
    raise ValueError("limit must be >= 0")

  now = _utc_now()
  start = period_start_date(now=now, period=period)

  async with session.begin():
    # Lock the current bucket row to prevent race conditions across requests/workers.
    stmt = select(UserQuotaBucket).where(UserQuotaBucket.user_id == user_id, UserQuotaBucket.metric_key == metric_key, UserQuotaBucket.period == period, UserQuotaBucket.period_start == start).with_for_update()
    result = await session.execute(stmt)
    bucket = result.scalar_one_or_none()

    if bucket is None:
      # Create the bucket row under the transaction so the lock scope is consistent.
      bucket = UserQuotaBucket(id=uuid.uuid4(), user_id=user_id, metric_key=metric_key, period=period, period_start=start, used=0, updated_at=now)
      session.add(bucket)
      await session.flush()

    new_used = int(bucket.used) + int(quantity)
    # Enforce hard limits when configured (0 means disabled).
    if normalized_limit == 0 or new_used > normalized_limit:
      remaining = max(normalized_limit - int(bucket.used), 0)
      raise QuotaExceededError(f"quota exceeded for {metric_key} ({remaining} remaining)")

    # Persist the updated counter.
    bucket.used = new_used
    bucket.updated_at = now
    session.add(bucket)
    # Record an append-only log for auditing and analytics.
    session.add(UserUsageLog(user_id=user_id, action_type=f"quota:{metric_key}", quantity=int(quantity), metadata_json=metadata))

  remaining = max(normalized_limit - new_used, 0)
  return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=new_used, remaining=remaining)


async def refund_quota(session: AsyncSession, *, user_id: uuid.UUID, metric_key: str, period: QuotaPeriod, quantity: int, limit: int, metadata: dict | None = None) -> QuotaSnapshot:
  """Refund quota to compensate for failed operations after a successful reservation.

  How/Why:
    - Some code paths reserve quota before enqueueing work to prevent races.
    - When enqueue fails (or an upstream error occurs), the system must compensate so users are not charged for work that never ran.
  """
  if quantity <= 0:
    raise ValueError("quantity must be positive.")
  normalized_limit = int(limit)
  if normalized_limit < 0:
    raise ValueError("limit must be >= 0")

  now = _utc_now()
  start = period_start_date(now=now, period=period)

  async with session.begin():
    stmt = select(UserQuotaBucket).where(UserQuotaBucket.user_id == user_id, UserQuotaBucket.metric_key == metric_key, UserQuotaBucket.period == period, UserQuotaBucket.period_start == start).with_for_update()
    result = await session.execute(stmt)
    bucket = result.scalar_one_or_none()
    if bucket is None:
      # If there is no bucket row, there is nothing to refund safely.
      return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=0, remaining=max(normalized_limit, 0))

    new_used = int(bucket.used) - int(quantity)
    if new_used < 0:
      new_used = 0
    bucket.used = new_used
    bucket.updated_at = now
    session.add(bucket)
    session.add(UserUsageLog(user_id=user_id, action_type=f"quota_refund:{metric_key}", quantity=int(quantity), metadata_json=metadata))

  remaining = max(normalized_limit - new_used, 0)
  return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=new_used, remaining=remaining)
