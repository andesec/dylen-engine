"""Feature flag services for evaluating and mutating flags at runtime."""

from __future__ import annotations

import re
import uuid

from app.config import get_settings
from app.schema.feature_flags import FeatureFlag, OrganizationFeatureFlag, SubscriptionTierFeatureFlag
from app.services.runtime_config import resolve_effective_runtime_config
from sqlalchemy import select
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


async def resolve_effective_feature_flags(session: AsyncSession, *, org_id: uuid.UUID | None, subscription_tier_id: int | None) -> dict[str, bool]:
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


async def is_feature_enabled(session: AsyncSession, *, key: str, org_id: uuid.UUID | None, subscription_tier_id: int | None) -> bool:
  """Return True when a feature flag is enabled for the given tenant/tier context."""
  # Use the merged evaluation so callers do not duplicate override logic.
  normalized = validate_flag_key(key)
  effective = await resolve_effective_feature_flags(session, org_id=org_id, subscription_tier_id=subscription_tier_id)
  return bool(effective.get(normalized, False))
