"""Quota resolution and consumption helpers."""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass

from app.schema.quotas import SubscriptionTier, UserTierOverride, UserUsageLog, UserUsageMetrics
from app.services.users import ensure_usage_row
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedQuota:
  """Resolved quota, total limits, and remaining counts for a user."""

  tier_name: str
  max_file_upload_kb: int | None
  highest_lesson_depth: str | None
  max_sections_per_lesson: int | None

  total_file_uploads: int | None
  total_image_uploads: int | None
  total_sections: int | None
  total_research: int | None

  remaining_file_uploads: int | None
  remaining_image_uploads: int | None
  remaining_sections: int | None
  remaining_research: int | None

  coach_mode_enabled: bool
  coach_voice_tier: str | None


async def get_active_override(session: AsyncSession, user_id: uuid.UUID) -> UserTierOverride | None:
  """Return an active override for the user if present."""
  # Restrict override selection to the active window to avoid stale promos.
  now = datetime.datetime.now(datetime.UTC)
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
    logger.warning("User usage row missing for user %s; lazy-creating.", user_id)
    await ensure_usage_row(session, user_id)
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

  def _calculate_limit_and_remaining(attr_name: str, usage_count: int) -> tuple[int | None, int | None]:
    val = _pick(attr_name)
    limit = int(val) if val is not None else None
    remaining = (limit - usage_count) if limit is not None else None
    return limit, remaining

  limit_files, remaining_files = _calculate_limit_and_remaining("file_upload_quota", usage.files_uploaded_count)
  limit_images, remaining_images = _calculate_limit_and_remaining("image_upload_quota", usage.images_uploaded_count)
  limit_sections, remaining_sections = _calculate_limit_and_remaining("gen_sections_quota", usage.sections_generated_count)
  limit_research, remaining_research = _calculate_limit_and_remaining("research_quota", usage.research_usage_count)

  return ResolvedQuota(
    tier_name=tier.name,
    max_file_upload_kb=_pick("max_file_upload_kb"),
    highest_lesson_depth=_pick("highest_lesson_depth"),
    max_sections_per_lesson=_pick("max_sections_per_lesson"),
    total_file_uploads=limit_files,
    total_image_uploads=limit_images,
    total_sections=limit_sections,
    total_research=limit_research,
    remaining_file_uploads=remaining_files,
    remaining_image_uploads=remaining_images,
    remaining_sections=remaining_sections,
    remaining_research=remaining_research,
    coach_mode_enabled=bool(_pick("coach_mode_enabled")),
    coach_voice_tier=_pick("coach_voice_tier"),
  )


async def _assert_positive(remaining: int | None, metric: str) -> None:
  """Raise if remaining quota is exhausted."""
  if remaining is not None and remaining <= 0:
    raise QuotaExceededError(f"{metric} quota exceeded")


async def _remaining_for_action(session: AsyncSession, *, usage: UserUsageMetrics, action: str) -> int | None:
  """Return remaining quota for a specific action using a single SQL projection."""
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
    "RESEARCH": (tier.research_quota, override.research_quota if override else None, usage.research_usage_count),
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
    now = datetime.datetime.now(datetime.UTC)
    usage.last_updated = now

    if action == "FILE_UPLOAD":
      usage.files_uploaded_count += quantity
    elif action == "IMAGE_UPLOAD":
      usage.images_uploaded_count += quantity
    elif action == "SECTION_GEN":
      usage.sections_generated_count += quantity
    elif action == "RESEARCH":
      usage.research_usage_count += quantity
    else:
      raise ValueError(f"Unsupported action {action}")

    session.add(usage)
    session.add(UserUsageLog(user_id=user_id, action_type=action, quantity=quantity, metadata_json=None))

  return await resolve_quota(session, user_id)
