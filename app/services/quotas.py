"""Quota resolution and consumption helpers."""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass, field

from app.config import get_settings
from app.schema.quotas import QuotaPeriod, SubscriptionTier, UserTierOverride, UserUsageMetrics
from app.schema.sql import User
from app.services.feature_flags import resolve_effective_feature_flags
from app.services.quota_buckets import get_quota_snapshot
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.users import ensure_usage_row
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuotaEntry:
  """A UI-friendly quota description including current availability.

  How/Why:
    - Clients need a stable, labeled representation of quotas to render UX copy.
    - Availability is computed server-side so clients don't re-implement quota logic.
    - Some quotas are configured before pipelines exist; those are marked as not tracked.
  """

  key: str
  label: str
  period: str | None
  limit: int
  used: int | None
  remaining: int | None
  available: bool
  tracked: bool


@dataclass(frozen=True)
class QuotaSummaryEntry:
  """Slim quota entry with only resource, total, and available counts."""

  resource: str
  total: int | None
  available: int | None


@dataclass(frozen=True)
class QuotaSummaryResponse:
  """Minimal quota response with optional detailed payload."""

  tier_name: str
  quotas: list[QuotaSummaryEntry] = field(default_factory=list)
  details: ResolvedQuota | None = None


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

  tutor_mode_enabled: bool
  tutor_voice_tier: str | None
  quota_entries: list[QuotaEntry] = field(default_factory=list)
  availability: dict[str, bool] = field(default_factory=dict)


def build_quota_summary(quota: ResolvedQuota) -> list[QuotaSummaryEntry]:
  """Create the minimal quota summary list for API responses."""
  # Seed summaries with basic tier quotas that are not tracked in buckets.
  summaries: list[QuotaSummaryEntry] = []
  # Filter base tier quotas so disabled or missing limits never appear in the response.
  base_candidates = [
    ("file_uploads", quota.total_file_uploads, quota.remaining_file_uploads),
    ("image_uploads", quota.total_image_uploads, quota.remaining_image_uploads),
    ("sections", quota.total_sections, quota.remaining_sections),
    ("research", quota.total_research, quota.remaining_research),
  ]
  # Keep only tier-enabled base quotas.
  for resource, total, available in base_candidates:
    # Drop resources that are not configured for the tier or are disabled.
    if total is None:
      continue
    if total <= 0:
      continue
    summaries.append(QuotaSummaryEntry(resource=resource, total=total, available=available))

  # Append bucket-based quotas so per-period limits are available to clients.
  for entry in quota.quota_entries:
    # Keep only tier-enabled bucket quotas, even when remaining is exhausted.
    if entry.limit <= 0:
      continue
    if not entry.available and entry.remaining != 0:
      continue
    summaries.append(QuotaSummaryEntry(resource=entry.key, total=entry.limit, available=entry.remaining))

  return summaries


async def get_active_override(session: AsyncSession, user_id: uuid.UUID) -> UserTierOverride | None:
  """Return an active override for the user if present."""
  # Restrict override selection to the active window to avoid stale promos.
  now = datetime.datetime.now(datetime.UTC)
  stmt = select(UserTierOverride).where(UserTierOverride.user_id == user_id, UserTierOverride.starts_at <= now, UserTierOverride.expires_at >= now).order_by(UserTierOverride.starts_at.desc(), UserTierOverride.id.desc()).limit(1)
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

  settings = get_settings()
  user = await session.get(User, user_id)
  org_id = user.org_id if user is not None else None
  flags = await resolve_effective_feature_flags(session, org_id=org_id, subscription_tier_id=int(usage.subscription_tier_id), user_id=user_id)
  runtime_config = await resolve_effective_runtime_config(session, settings=settings, org_id=org_id, subscription_tier_id=int(usage.subscription_tier_id), user_id=None)

  async def _bucket_entry(*, key: str, label: str, period: QuotaPeriod, limit_key: str, metric_key: str, feature_flag: str | None = None) -> QuotaEntry | None:
    # Deny-by-default: missing config means limit 0 => unavailable.
    limit = int(runtime_config.get(limit_key) or 0)
    snapshot = await get_quota_snapshot(session, user_id=user_id, metric_key=metric_key, period=period, limit=limit)
    feature_enabled = True if feature_flag is None else bool(flags.get(feature_flag) is True)
    if not feature_enabled:
      return None
    available = bool(feature_enabled and snapshot.remaining > 0 and limit > 0)
    return QuotaEntry(key=key, label=label, period=str(period.value), limit=limit, used=int(snapshot.used), remaining=int(snapshot.remaining), available=available, tracked=True)

  def _untracked_entry(*, key: str, label: str, period: str | None, limit_key: str, feature_flag: str | None = None) -> QuotaEntry | None:
    # Untracked quotas are configured for future pipelines; usage is not enforced yet.
    limit = int(runtime_config.get(limit_key) or 0)
    feature_enabled = True if feature_flag is None else bool(flags.get(feature_flag) is True)
    if not feature_enabled:
      return None
    available = bool(feature_enabled and limit > 0)
    return QuotaEntry(key=key, label=label, period=str(period) if period is not None else None, limit=limit, used=None, remaining=None if limit <= 0 else limit, available=available, tracked=False)

  quota_candidates: list[QuotaEntry | None] = [
    await _bucket_entry(key="lesson.generate", label="Lesson Limit", period=QuotaPeriod.WEEK, limit_key="limits.lessons_per_week", metric_key="lesson.generate"),
    await _bucket_entry(key="section.generate", label="Section Limit", period=QuotaPeriod.MONTH, limit_key="limits.sections_per_month", metric_key="section.generate"),
    await _bucket_entry(key="tutor.generate", label="Tutor Limit", period=QuotaPeriod.MONTH, limit_key="limits.tutor_sections_per_month", metric_key="tutor.generate"),
    await _bucket_entry(key="fenster.widget.generate", label="Fenster Widget Limit", period=QuotaPeriod.MONTH, limit_key="limits.fenster_widgets_per_month", metric_key="fenster.widget.generate"),
    await _bucket_entry(key="ocr.extract", label="OCR Extract Limit", period=QuotaPeriod.MONTH, limit_key="limits.ocr_files_per_month", metric_key="ocr.extract", feature_flag="feature.ocr"),
    await _bucket_entry(key="writing.check", label="Writing Check Limit", period=QuotaPeriod.MONTH, limit_key="limits.writing_checks_per_month", metric_key="writing.check", feature_flag="feature.writing"),
    await _bucket_entry(key="youtube.capture.minutes", label="YouTube Capture Minutes", period=QuotaPeriod.MONTH, limit_key="limits.youtube_capture_minutes_per_month", metric_key="youtube.capture.minutes", feature_flag="feature.youtube_capture"),
    await _bucket_entry(key="image.generate", label="Image Generation Limit", period=QuotaPeriod.MONTH, limit_key="limits.image_generations_per_month", metric_key="image.generate", feature_flag="feature.image_generation"),
    _untracked_entry(key="tutor.active.tokens", label="Tutor (Active) Token Cap", period="MONTH", limit_key="tutor.active_tokens_per_month", feature_flag="feature.tutor.active"),
    _untracked_entry(key="career.mock_exam.tokens", label="Mock Exams Token Cap", period="MONTH", limit_key="career.mock_exams_token_cap", feature_flag="feature.mock_exams"),
    _untracked_entry(key="career.mock_interview.minutes", label="Mock Interviews Minutes Cap", period="MONTH", limit_key="career.mock_interviews_minutes_cap", feature_flag="feature.mock_interviews"),
  ]
  quota_entries = [entry for entry in quota_candidates if entry is not None]
  availability = {entry.key: bool(entry.available) for entry in quota_entries}

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
    tutor_mode_enabled=bool(_pick("tutor_mode_enabled")),
    tutor_voice_tier=_pick("tutor_voice_tier"),
    quota_entries=quota_entries,
    availability=availability,
  )
