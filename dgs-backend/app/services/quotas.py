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


async def _remaining_for_action(session: AsyncSession, *, usage: UserUsageMetrics, action: str) -> int | None:
  """Return remaining quota for a specific action using a single SQL projection."""
  now = datetime.datetime.utcnow()
  user_id = usage.user_id

  # Fetch the subscription tier for the user
  tier = await session.get(SubscriptionTier, usage.subscription_tier_id)
  if not tier:
     # Fallback or error if tier is missing? For robustness, raising error is safer
     raise RuntimeError(f"Subscription tier {usage.subscription_tier_id} not found")

  # Fetch active override if any
  override = await get_active_override(session, user_id)

  mapping = {
    "FILE_UPLOAD": (tier.file_upload_quota, override.file_upload_quota if override else None, usage.files_uploaded_count),
    "IMAGE_UPLOAD": (tier.image_upload_quota, override.image_upload_quota if override else None, usage.images_uploaded_count),
    "SECTION_GEN": (tier.gen_sections_quota, override.gen_sections_quota if override else None, usage.sections_generated_count),
  }
  
  if action not in mapping:
    raise ValueError(f"Unsupported action {action}")

  tier_val, override_val, usage_val = mapping[action]
  
  limit = override_val if override_val is not None else tier_val
  
  # If limit is None (unlimited), return None
  if limit is None:
      return None
      
  return limit - usage_val


class QuotaExceededError(RuntimeError):
  """Raised when a quota would be exceeded."""


async def consume_quota(session: AsyncSession, *, user_id: uuid.UUID, action: str, quantity: int = 1) -> ResolvedQuota:
  """Atomically check and consume quota, logging the action."""
  if quantity <= 0:
    raise ValueError("Quantity must be positive.")

  # Transactional block with pessimistic locking to prevent race conditions
  async with session.begin():
      # Acquire lock on the usage row
      usage = await session.get(UserUsageMetrics, user_id, with_for_update=True)
      if not usage:
           raise RuntimeError(f"User usage row not found for user {user_id}")

      remaining = await _remaining_for_action(session, usage=usage, action=action)
      
      # Check quota
      if remaining is not None and remaining < quantity:
          raise QuotaExceededError(f"{action.lower()} quota exceeded (requested {quantity}, remaining {remaining})")

      # Apply update
      now = datetime.datetime.now(datetime.timezone.utc)
      usage.last_updated = now
      
      if action == "FILE_UPLOAD":
        usage.files_uploaded_count += quantity
      elif action == "IMAGE_UPLOAD":
        usage.images_uploaded_count += quantity
      elif action == "SECTION_GEN":
        usage.sections_generated_count += quantity
      else:
        raise ValueError(f"Unsupported action {action}")
      
      session.add(usage)
      session.add(UserUsageLog(user_id=user_id, action_type=action, quantity=quantity, metadata_json=None))

  return await resolve_quota(session, user_id)
