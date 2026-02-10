"""Feature flag services for evaluating and mutating flags at runtime."""

from __future__ import annotations

import datetime
import re
import uuid

from app.config import get_settings
from app.schema.feature_flags import FeatureFlag, OrganizationFeatureFlag, SubscriptionTierFeatureFlag, UserFeatureFlagOverride
from app.services.runtime_config import resolve_effective_runtime_config
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

_FLAG_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")


def validate_flag_key(key: str) -> str:
  """Validate and normalize a feature flag key."""
  # Normalize inputs so DB keys remain consistent.
  normalized = (key or "").strip().lower()
  if not normalized or not _FLAG_KEY_RE.match(normalized):
    raise ValueError("Invalid feature flag key format.")
  return normalized


async def list_feature_flags(session: AsyncSession) -> list[FeatureFlag]:
  """List all feature flag definitions."""
  # Keep listing simple so the admin UI can render quickly.
  result = await session.execute(select(FeatureFlag).order_by(FeatureFlag.key.asc()))
  return list(result.scalars().all())


async def get_feature_flag_by_key(session: AsyncSession, *, key: str) -> FeatureFlag | None:
  """Fetch a feature flag definition by key."""
  # Use a direct lookup so evaluation can short-circuit when missing.
  normalized = validate_flag_key(key)
  result = await session.execute(select(FeatureFlag).where(FeatureFlag.key == normalized))
  return result.scalar_one_or_none()


async def create_feature_flag(session: AsyncSession, *, key: str, description: str | None, default_enabled: bool) -> FeatureFlag:
  """Create a feature flag definition."""
  # Validate key before writing to avoid inconsistent rows.
  normalized = validate_flag_key(key)
  flag = FeatureFlag(key=normalized, description=description, default_enabled=default_enabled)
  session.add(flag)
  await session.commit()
  await session.refresh(flag)
  return flag


async def set_feature_flag_default_enabled(session: AsyncSession, *, key: str, enabled: bool) -> FeatureFlag | None:
  """Update a feature flag global default enablement value by key."""
  # Normalize lookup key to guarantee deterministic matching.
  normalized = validate_flag_key(key)
  result = await session.execute(select(FeatureFlag).where(FeatureFlag.key == normalized))
  flag = result.scalar_one_or_none()
  if flag is None:
    return None
  # Persist the updated default so global evaluation reflects the toggle.
  flag.default_enabled = enabled
  await session.commit()
  await session.refresh(flag)
  return flag


async def set_tier_feature_flag(session: AsyncSession, *, subscription_tier_id: int, feature_flag_id: uuid.UUID, enabled: bool) -> None:
  """Upsert a subscription-tier feature flag override."""
  # Persist tier defaults so new users inherit the intended capabilities.
  stmt = insert(SubscriptionTierFeatureFlag).values(subscription_tier_id=subscription_tier_id, feature_flag_id=feature_flag_id, enabled=enabled)
  stmt = stmt.on_conflict_do_update(index_elements=["subscription_tier_id", "feature_flag_id"], set_={"enabled": enabled})
  await session.execute(stmt)
  await session.commit()


async def set_org_feature_flag(session: AsyncSession, *, org_id: uuid.UUID, feature_flag_id: uuid.UUID, enabled: bool) -> None:
  """Upsert an organization feature flag override."""
  # Persist tenant overrides so admins can toggle features without redeploy.
  stmt = insert(OrganizationFeatureFlag).values(org_id=org_id, feature_flag_id=feature_flag_id, enabled=enabled)
  stmt = stmt.on_conflict_do_update(index_elements=["org_id", "feature_flag_id"], set_={"enabled": enabled})
  await session.execute(stmt)
  await session.commit()


async def set_user_feature_flag_override(session: AsyncSession, *, user_id: uuid.UUID, feature_flag_id: uuid.UUID, enabled: bool, starts_at: datetime.datetime, expires_at: datetime.datetime) -> None:
  """Upsert a per-user feature flag override for promo windows."""
  # Persist user-specific overrides so temporary promos can enable/disable features.
  stmt = insert(UserFeatureFlagOverride).values(user_id=user_id, feature_flag_id=feature_flag_id, enabled=enabled, starts_at=starts_at, expires_at=expires_at)
  stmt = stmt.on_conflict_do_update(constraint="ux_user_feature_flag_overrides_user_flag", set_={"enabled": enabled, "starts_at": starts_at, "expires_at": expires_at})
  await session.execute(stmt)
  await session.commit()


async def delete_user_feature_flag_overrides(session: AsyncSession, *, user_id: uuid.UUID) -> None:
  """Delete per-user feature flag overrides for an account."""
  # Remove promo overrides so user-level feature behavior falls back to tier/org defaults.
  await session.execute(delete(UserFeatureFlagOverride).where(UserFeatureFlagOverride.user_id == user_id))
  await session.commit()


async def list_active_user_feature_overrides(session: AsyncSession, *, user_id: uuid.UUID, at: datetime.datetime | None = None) -> dict[str, bool]:
  """Return active per-user feature overrides keyed by flag key."""
  # Resolve active-time defaults in UTC so promo windows are evaluated consistently.
  active_at = at or datetime.datetime.now(datetime.UTC)
  stmt = (
    select(FeatureFlag.key, UserFeatureFlagOverride.enabled)
    .join(UserFeatureFlagOverride, UserFeatureFlagOverride.feature_flag_id == FeatureFlag.id)
    .where(UserFeatureFlagOverride.user_id == user_id, UserFeatureFlagOverride.starts_at <= active_at, UserFeatureFlagOverride.expires_at >= active_at)
  )
  result = await session.execute(stmt)
  rows = result.fetchall()
  # Convert rows to a plain dict for stable downstream resolution.
  return {str(key): bool(enabled) for key, enabled in rows}


async def resolve_effective_feature_flags(session: AsyncSession, *, org_id: uuid.UUID | None, subscription_tier_id: int | None, user_id: uuid.UUID | None = None) -> dict[str, bool]:
  """Resolve effective feature flags by merging global defaults, tier defaults, then org overrides."""
  # Start from global defaults so missing overrides remain predictable.
  flags_result = await session.execute(select(FeatureFlag))
  flags = list(flags_result.scalars().all())
  effective: dict[str, bool] = {flag.key: bool(flag.default_enabled) for flag in flags}

  # Apply subscription tier overrides before tenant-specific overrides.
  if subscription_tier_id is not None:
    tier_stmt = select(FeatureFlag.key, SubscriptionTierFeatureFlag.enabled).join(SubscriptionTierFeatureFlag, SubscriptionTierFeatureFlag.feature_flag_id == FeatureFlag.id).where(SubscriptionTierFeatureFlag.subscription_tier_id == subscription_tier_id)
    tier_result = await session.execute(tier_stmt)
    for key, enabled in tier_result.fetchall():
      effective[str(key)] = bool(enabled)

  # Apply tenant overrides last so tenants can disable tier-enabled features.
  if org_id is not None:
    org_stmt = select(FeatureFlag.key, OrganizationFeatureFlag.enabled).join(OrganizationFeatureFlag, OrganizationFeatureFlag.feature_flag_id == FeatureFlag.id).where(OrganizationFeatureFlag.org_id == org_id)
    org_result = await session.execute(org_stmt)
    for key, enabled in org_result.fetchall():
      effective[str(key)] = bool(enabled)

  # Apply user overrides after org overrides so promos can target specific accounts.
  if user_id is not None:
    user_overrides = await list_active_user_feature_overrides(session, user_id=user_id)
    for key, enabled in user_overrides.items():
      effective[key] = enabled

  # Apply global disables last so super-admin toggles always win.
  settings = get_settings()
  global_config = await resolve_effective_runtime_config(session, settings=settings, org_id=None, subscription_tier_id=None, user_id=None)
  disabled_keys = global_config.get("features.disabled_global") or []
  for disabled_key in disabled_keys:
    normalized = validate_flag_key(str(disabled_key))
    effective[normalized] = False

  return effective


async def resolve_global_disabled_features(session: AsyncSession) -> set[str]:
  """Return globally disabled feature keys for response redaction."""
  settings = get_settings()
  global_config = await resolve_effective_runtime_config(session, settings=settings, org_id=None, subscription_tier_id=None, user_id=None)
  disabled_keys = global_config.get("features.disabled_global") or []
  normalized: set[str] = set()
  for disabled_key in disabled_keys:
    normalized.add(validate_flag_key(str(disabled_key)))
  return normalized


async def is_feature_enabled(session: AsyncSession, *, key: str, org_id: uuid.UUID | None, subscription_tier_id: int | None, user_id: uuid.UUID | None = None) -> bool:
  """Return True when a feature flag is enabled for the given tenant/tier context."""
  # Use the merged evaluation so callers do not duplicate override logic.
  normalized = validate_flag_key(key)
  effective = await resolve_effective_feature_flags(session, org_id=org_id, subscription_tier_id=subscription_tier_id, user_id=user_id)
  return bool(effective.get(normalized, False))
