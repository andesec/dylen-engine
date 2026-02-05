"""Quota bucket services for period-based enforcement and logging."""

from __future__ import annotations

import datetime
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.schema.quotas import QuotaPeriod, UserQuotaBucket, UserQuotaReservation, UserUsageLog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
  reserved: int
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


@asynccontextmanager
async def _quota_transaction(session: AsyncSession):
  """Start a transaction appropriate for the current session state.

  How/Why:
    - SQLAlchemy AsyncSession autobegins on the first statement, so a new
      explicit begin() inside the same request can raise InvalidRequestError.
    - Use a SAVEPOINT when already inside a transaction to keep atomicity.
  """
  # Use a nested transaction when an outer transaction is already active.
  if session.in_transaction():
    async with session.begin_nested():
      yield
    return
  # Start a new transaction when none is active on the session.
  async with session.begin():
    yield


async def get_quota_snapshot(session: AsyncSession, *, user_id: uuid.UUID, metric_key: str, period: QuotaPeriod, limit: int) -> QuotaSnapshot:
  """Return current used/remaining for the active period for a metric."""
  # Normalize limits so callers can treat zero as disabled.
  normalized_limit = int(limit)
  if normalized_limit < 0:
    raise ValueError("limit must be >= 0")

  now = _utc_now()
  start = period_start_date(now=now, period=period)
  stmt = select(UserQuotaBucket.used, UserQuotaBucket.reserved).where(UserQuotaBucket.user_id == user_id, UserQuotaBucket.metric_key == metric_key, UserQuotaBucket.period == period, UserQuotaBucket.period_start == start)
  result = await session.execute(stmt)
  row = result.one_or_none()
  used = int(getattr(row, "used", 0) or 0)
  reserved = int(getattr(row, "reserved", 0) or 0)
  remaining = max(normalized_limit - used - reserved, 0)
  return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=used, reserved=reserved, remaining=remaining)


async def reserve_quota(session: AsyncSession, *, user_id: uuid.UUID, metric_key: str, period: QuotaPeriod, quantity: int, limit: int, job_id: str, section_index: int | None = None, metadata: dict | None = None) -> QuotaSnapshot:
  """Reserve quota for a metric and append a usage log entry."""
  # Enforce positive reservation sizes so counts remain consistent.
  if quantity <= 0:
    raise ValueError("quantity must be positive.")
  # Normalize limit values so negative inputs fail fast.
  normalized_limit = int(limit)
  if normalized_limit < 0:
    raise ValueError("limit must be >= 0")

  now = _utc_now()
  start = period_start_date(now=now, period=period)

  async with _quota_transaction(session):
    # Lock the bucket row to keep reservations consistent under concurrency.
    stmt = select(UserQuotaBucket).where(UserQuotaBucket.user_id == user_id, UserQuotaBucket.metric_key == metric_key, UserQuotaBucket.period == period, UserQuotaBucket.period_start == start).with_for_update()
    result = await session.execute(stmt)
    bucket = result.scalar_one_or_none()

    if bucket is None:
      # Create the bucket under the same transaction to avoid race conditions.
      bucket = UserQuotaBucket(id=uuid.uuid4(), user_id=user_id, metric_key=metric_key, period=period, period_start=start, used=0, reserved=0, updated_at=now)
      session.add(bucket)
      await session.flush()

    # Check for an existing reservation to make this call idempotent.
    # Compose reservation filters to keep the query readable.
    existing_filters = [
      UserQuotaReservation.user_id == user_id,
      UserQuotaReservation.metric_key == metric_key,
      UserQuotaReservation.period == period,
      UserQuotaReservation.period_start == start,
      UserQuotaReservation.job_id == job_id,
      UserQuotaReservation.section_index == section_index,
    ]
    existing_stmt = select(UserQuotaReservation).where(*existing_filters)
    existing_result = await session.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
      remaining = max(normalized_limit - int(bucket.used) - int(bucket.reserved), 0)
      return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=int(bucket.used), reserved=int(bucket.reserved), remaining=remaining)

    # Enforce remaining capacity before reserving.
    remaining = max(normalized_limit - int(bucket.used) - int(bucket.reserved), 0)
    if normalized_limit == 0 or remaining < int(quantity):
      raise QuotaExceededError(f"quota exceeded for {metric_key} ({remaining} remaining)")

    bucket.reserved = int(bucket.reserved) + int(quantity)
    bucket.updated_at = now
    session.add(bucket)

    # Persist the reservation record and usage log inside the same transaction.
    session.add(UserQuotaReservation(user_id=user_id, metric_key=metric_key, period=period, period_start=start, quantity=int(quantity), job_id=job_id, section_index=section_index))
    session.add(UserUsageLog(user_id=user_id, action_type=f"quota_reserve:{metric_key}", quantity=int(quantity), metadata_json=metadata))

    # Flush to surface uniqueness errors while the transaction is active.
    try:
      await session.flush()
    except IntegrityError:
      # Roll back the reservation bump if a concurrent reservation already exists.
      await session.rollback()
      return await get_quota_snapshot(session, user_id=user_id, metric_key=metric_key, period=period, limit=normalized_limit)

  remaining = max(normalized_limit - int(bucket.used) - int(bucket.reserved), 0)
  return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=int(bucket.used), reserved=int(bucket.reserved), remaining=remaining)


async def commit_quota_reservation(session: AsyncSession, *, user_id: uuid.UUID, metric_key: str, period: QuotaPeriod, quantity: int, limit: int, job_id: str, section_index: int | None = None, metadata: dict | None = None) -> QuotaSnapshot:
  """Commit a previously reserved quota entry and append a usage log entry."""
  # Enforce positive quantities so the commit adjusts counters predictably.
  if quantity <= 0:
    raise ValueError("quantity must be positive.")
  # Normalize limits and reject invalid configurations.
  normalized_limit = int(limit)
  if normalized_limit < 0:
    raise ValueError("limit must be >= 0")

  now = _utc_now()
  start = period_start_date(now=now, period=period)

  async with _quota_transaction(session):
    # Lock the bucket row so reserved/used transitions are atomic.
    stmt = select(UserQuotaBucket).where(UserQuotaBucket.user_id == user_id, UserQuotaBucket.metric_key == metric_key, UserQuotaBucket.period == period, UserQuotaBucket.period_start == start).with_for_update()
    result = await session.execute(stmt)
    bucket = result.scalar_one_or_none()
    if bucket is None:
      # Missing bucket indicates a logic error; treat as quota exceeded.
      raise QuotaExceededError(f"quota bucket missing for {metric_key}")

    # Compose reservation filters to keep the query readable.
    reservation_filters = [
      UserQuotaReservation.user_id == user_id,
      UserQuotaReservation.metric_key == metric_key,
      UserQuotaReservation.period == period,
      UserQuotaReservation.period_start == start,
      UserQuotaReservation.job_id == job_id,
      UserQuotaReservation.section_index == section_index,
    ]
    reservation_stmt = select(UserQuotaReservation).where(*reservation_filters).with_for_update()
    reservation_result = await session.execute(reservation_stmt)
    reservation = reservation_result.scalar_one_or_none()
    if reservation is None:
      remaining = max(normalized_limit - int(bucket.used) - int(bucket.reserved), 0)
      return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=int(bucket.used), reserved=int(bucket.reserved), remaining=remaining)

    bucket.reserved = max(int(bucket.reserved) - int(quantity), 0)
    bucket.used = int(bucket.used) + int(quantity)
    bucket.updated_at = now
    session.add(bucket)
    await session.delete(reservation)
    session.add(UserUsageLog(user_id=user_id, action_type=f"quota:{metric_key}", quantity=int(quantity), metadata_json=metadata))

  remaining = max(normalized_limit - int(bucket.used) - int(bucket.reserved), 0)
  return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=int(bucket.used), reserved=int(bucket.reserved), remaining=remaining)


async def release_quota_reservation(session: AsyncSession, *, user_id: uuid.UUID, metric_key: str, period: QuotaPeriod, quantity: int, limit: int, job_id: str, section_index: int | None = None, metadata: dict | None = None) -> QuotaSnapshot:
  """Release a previously reserved quota entry and append a usage log entry."""
  # Enforce positive quantities to keep release semantics consistent.
  if quantity <= 0:
    raise ValueError("quantity must be positive.")
  # Normalize limits and reject invalid configurations.
  normalized_limit = int(limit)
  if normalized_limit < 0:
    raise ValueError("limit must be >= 0")

  now = _utc_now()
  start = period_start_date(now=now, period=period)

  async with _quota_transaction(session):
    # Lock the bucket row so reserved counters are accurate.
    stmt = select(UserQuotaBucket).where(UserQuotaBucket.user_id == user_id, UserQuotaBucket.metric_key == metric_key, UserQuotaBucket.period == period, UserQuotaBucket.period_start == start).with_for_update()
    result = await session.execute(stmt)
    bucket = result.scalar_one_or_none()
    if bucket is None:
      remaining = max(normalized_limit, 0)
      return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=0, reserved=0, remaining=remaining)

    # Compose reservation filters to keep the query readable.
    reservation_filters = [
      UserQuotaReservation.user_id == user_id,
      UserQuotaReservation.metric_key == metric_key,
      UserQuotaReservation.period == period,
      UserQuotaReservation.period_start == start,
      UserQuotaReservation.job_id == job_id,
      UserQuotaReservation.section_index == section_index,
    ]
    reservation_stmt = select(UserQuotaReservation).where(*reservation_filters).with_for_update()
    reservation_result = await session.execute(reservation_stmt)
    reservation = reservation_result.scalar_one_or_none()
    if reservation is None:
      remaining = max(normalized_limit - int(bucket.used) - int(bucket.reserved), 0)
      return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=int(bucket.used), reserved=int(bucket.reserved), remaining=remaining)

    bucket.reserved = max(int(bucket.reserved) - int(quantity), 0)
    bucket.updated_at = now
    session.add(bucket)
    await session.delete(reservation)
    session.add(UserUsageLog(user_id=user_id, action_type=f"quota_release:{metric_key}", quantity=int(quantity), metadata_json=metadata))

  remaining = max(normalized_limit - int(bucket.used) - int(bucket.reserved), 0)
  return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=int(bucket.used), reserved=int(bucket.reserved), remaining=remaining)


async def consume_quota(session: AsyncSession, *, user_id: uuid.UUID, metric_key: str, period: QuotaPeriod, quantity: int, limit: int, metadata: dict | None = None) -> QuotaSnapshot:
  """Atomically consume quota for a metric and append a usage log entry."""
  if quantity <= 0:
    raise ValueError("quantity must be positive.")
  normalized_limit = int(limit)
  if normalized_limit < 0:
    raise ValueError("limit must be >= 0")

  now = _utc_now()
  start = period_start_date(now=now, period=period)

  async with _quota_transaction(session):
    # Lock the current bucket row to prevent race conditions across requests/workers.
    stmt = select(UserQuotaBucket).where(UserQuotaBucket.user_id == user_id, UserQuotaBucket.metric_key == metric_key, UserQuotaBucket.period == period, UserQuotaBucket.period_start == start).with_for_update()
    result = await session.execute(stmt)
    bucket = result.scalar_one_or_none()

    if bucket is None:
      # Create the bucket row under the transaction so the lock scope is consistent.
      bucket = UserQuotaBucket(id=uuid.uuid4(), user_id=user_id, metric_key=metric_key, period=period, period_start=start, used=0, reserved=0, updated_at=now)
      session.add(bucket)
      await session.flush()

    new_used = int(bucket.used) + int(quantity)
    # Enforce hard limits when configured (0 means disabled).
    remaining_before = max(normalized_limit - int(bucket.used) - int(bucket.reserved), 0)
    if normalized_limit == 0 or int(quantity) > remaining_before:
      remaining = max(normalized_limit - int(bucket.used) - int(bucket.reserved), 0)
      raise QuotaExceededError(f"quota exceeded for {metric_key} ({remaining} remaining)")

    # Persist the updated counter.
    bucket.used = new_used
    bucket.updated_at = now
    session.add(bucket)
    # Record an append-only log for auditing and analytics.
    session.add(UserUsageLog(user_id=user_id, action_type=f"quota:{metric_key}", quantity=int(quantity), metadata_json=metadata))

  remaining = max(normalized_limit - new_used - int(bucket.reserved), 0)
  return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=new_used, reserved=int(bucket.reserved), remaining=remaining)


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

  async with _quota_transaction(session):
    stmt = select(UserQuotaBucket).where(UserQuotaBucket.user_id == user_id, UserQuotaBucket.metric_key == metric_key, UserQuotaBucket.period == period, UserQuotaBucket.period_start == start).with_for_update()
    result = await session.execute(stmt)
    bucket = result.scalar_one_or_none()
    if bucket is None:
      # If there is no bucket row, there is nothing to refund safely.
      return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=0, reserved=0, remaining=max(normalized_limit, 0))

    new_used = int(bucket.used) - int(quantity)
    if new_used < 0:
      new_used = 0
    bucket.used = new_used
    bucket.updated_at = now
    session.add(bucket)
    session.add(UserUsageLog(user_id=user_id, action_type=f"quota_refund:{metric_key}", quantity=int(quantity), metadata_json=metadata))

  remaining = max(normalized_limit - new_used - int(bucket.reserved), 0)
  return QuotaSnapshot(metric_key=metric_key, period=period, period_start=start, limit=normalized_limit, used=new_used, reserved=int(bucket.reserved), remaining=remaining)
