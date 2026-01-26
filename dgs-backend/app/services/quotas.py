"""Quota resolution and consumption helpers."""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.schema.quotas import SubscriptionTier, UserTierOverride, UserUsageLog, UserUsageMetrics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedQuota:
  """Resolved quota and remaining counts for a user."""

  tier_name: str
  max_file_upload_kb: int | None
  highest_lesson_depth: str | None
  max_sections_per_lesson: int | None
  remaining_file_uploads: int | None
  remaining_image_uploads: int | None
  remaining_sections: int | None
  coach_mode_enabled: bool
  coach_voice_tier: str | None


async def get_active_override(session: AsyncSession, user_id: uuid.UUID) -> UserTierOverride | None:
  """Return an active override for the user if present."""
  # Restrict override selection to the active window to avoid stale promos.
  now = datetime.datetime.now(datetime.timezone.utc)
  stmt = select(UserTierOverride).where(UserTierOverride.user_id == user_id, UserTierOverride.starts_at <= now, UserTierOverride.expires_at >= now)
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


async def resolve_quota(session: AsyncSession, user_id: uuid.UUID) -> ResolvedQuota:
  """Resolve effective quotas by merging base tier with any active override."""
  # Join usage with tier metadata in one query to avoid redundant lookups.
  usage_stmt = select(UserUsageMetrics, SubscriptionTier).join(SubscriptionTier, SubscriptionTier.id == UserUsageMetrics.subscription_tier_id).where(UserUsageMetrics.user_id == user_id)
  usage_result = await session.execute(usage_stmt)
  row = usage_result.one_or_none()
  if row is None:
    raise RuntimeError("User usage row missing; run backfill.")
  usage: UserUsageMetrics = row.UserUsageMetrics
  tier: SubscriptionTier = row.SubscriptionTier

  override = await get_active_override(session, user_id)

  def _pick(attr: str, *, default: bool = False) -> bool | int | str | None:
    # Prefer override values when present to honor promos.
    value = getattr(override, attr) if override else None
    return value if value is not None else getattr(tier, attr)

  remaining_files = None if _pick("file_upload_quota") is None else int(_pick("file_upload_quota")) - usage.files_uploaded_count
  remaining_images = None if _pick("image_upload_quota") is None else int(_pick("image_upload_quota")) - usage.images_uploaded_count
  remaining_sections = None if _pick("gen_sections_quota") is None else int(_pick("gen_sections_quota")) - usage.sections_generated_count

  return ResolvedQuota(
    tier_name=tier.name,
    max_file_upload_kb=_pick("max_file_upload_kb"),
    highest_lesson_depth=_pick("highest_lesson_depth"),
    max_sections_per_lesson=_pick("max_sections_per_lesson"),
    remaining_file_uploads=remaining_files,
    remaining_image_uploads=remaining_images,
    remaining_sections=remaining_sections,
    coach_mode_enabled=bool(_pick("coach_mode_enabled")),
    coach_voice_tier=_pick("coach_voice_tier"),
  )


async def _assert_positive(remaining: int | None, metric: str) -> None:
  """Raise if remaining quota is exhausted."""
  if remaining is not None and remaining <= 0:
    raise QuotaExceededError(f"{metric} quota exceeded")


async def _remaining_for_action(session: AsyncSession, *, user_id: uuid.UUID, action: str) -> int | None:
  """Return remaining quota for a specific action using a single SQL projection."""
  now = datetime.datetime.utcnow()
  mapping = {
    "FILE_UPLOAD": (SubscriptionTier.file_upload_quota, UserTierOverride.file_upload_quota, UserUsageMetrics.files_uploaded_count),
    "IMAGE_UPLOAD": (SubscriptionTier.image_upload_quota, UserTierOverride.image_upload_quota, UserUsageMetrics.images_uploaded_count),
    "SECTION_GEN": (SubscriptionTier.gen_sections_quota, UserTierOverride.gen_sections_quota, UserUsageMetrics.sections_generated_count),
  }
  if action not in mapping:
    raise ValueError(f"Unsupported action {action}")
  tier_col, override_col, usage_col = mapping[action]
  stmt = (
    select((func.coalesce(override_col, tier_col) - usage_col).label("remaining"))
    .select_from(UserUsageMetrics)
    .join(SubscriptionTier, SubscriptionTier.id == UserUsageMetrics.subscription_tier_id)
    .outerjoin(UserTierOverride, (UserTierOverride.user_id == user_id) & (UserTierOverride.starts_at <= now) & (UserTierOverride.expires_at >= now))
    .where(UserUsageMetrics.user_id == user_id)
  )
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


class QuotaExceededError(RuntimeError):
  """Raised when a quota would be exceeded."""


async def consume_quota(session: AsyncSession, *, user_id: uuid.UUID, action: str, quantity: int = 1) -> ResolvedQuota:
  """Atomically check and consume quota, logging the action."""
  if quantity <= 0:
    raise ValueError("Quantity must be positive.")

  # Compute remaining in SQL to reflect overrides and current usage.
  remaining = await _remaining_for_action(session, user_id=user_id, action=action)
  await _assert_positive(remaining, action.lower())

  # Perform atomic update and log within a transaction.
  now = func.now()
  update_values = {}
  if action == "FILE_UPLOAD":
    update_values["files_uploaded_count"] = UserUsageMetrics.files_uploaded_count + quantity
  if action == "IMAGE_UPLOAD":
    update_values["images_uploaded_count"] = UserUsageMetrics.images_uploaded_count + quantity
  if action == "SECTION_GEN":
    update_values["sections_generated_count"] = UserUsageMetrics.sections_generated_count + quantity

  if not update_values:
    raise ValueError(f"Unsupported action {action}")

  async with session.begin():
    await session.execute(UserUsageMetrics.__table__.update().where(UserUsageMetrics.user_id == user_id).values(**update_values, last_updated=now))
    session.add(UserUsageLog(user_id=user_id, action_type=action, quantity=quantity, metadata_json=None))

  return await resolve_quota(session, user_id)
