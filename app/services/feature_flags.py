"""Feature flag services for evaluating and mutating flags at runtime."""

from __future__ import annotations

import datetime
import re
import uuid
from dataclasses import dataclass

from app.config import get_settings
from app.schema.feature_flags import FeatureFlag, OrganizationFeatureFlag, SubscriptionTierFeatureFlag, UserFeatureFlagOverride
from app.schema.quotas import SubscriptionTier
from app.schema.sql import Permission
from app.services.runtime_config import resolve_effective_runtime_config
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

_FLAG_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")
FEATURE_REASON_GLOBAL_DISABLED = "GLOBAL_DISABLED"
FEATURE_REASON_TIER_DISABLED = "TIER_DISABLED"
FEATURE_REASON_TENANT_DISABLED = "TENANT_DISABLED"
FEATURE_REASON_PROMO_DISABLED = "PROMO_DISABLED"
FEATURE_REASON_MISCONFIGURED = "MISCONFIGURED"


@dataclass(frozen=True)
class FeatureFlagDecision:
  """Structured feature-flag decision payload used by APIs and security checks."""

  key: str
  enabled: bool
  reason_code: str | None
  global_enabled: bool
  tier_enabled: bool | None
  tier_record_exists: bool
  tenant_enabled: bool | None
  tenant_record_exists: bool
  promo_enabled: bool | None
  promo_record_exists: bool
  is_tenant_tier: bool | None
  is_tenant_context: bool
  missing_scope: str | None = None


def feature_flag_to_permission_slug(key: str) -> str:
  """Convert a feature flag key into a permission slug."""
  normalized = validate_flag_key(key)
  suffix = normalized[8:] if normalized.startswith("feature.") else normalized
  suffix = suffix.replace(".", "_").replace("-", "_").replace(":", "_").strip("_")
  return f"feature_{suffix}:use"


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
  # Keep feature permissions synchronized with feature definitions.
  permission_slug = feature_flag_to_permission_slug(normalized)
  permission_display = f"Use {normalized}"
  permission_description = f"Access endpoints gated by feature flag `{normalized}`."
  permission_stmt = insert(Permission).values(id=uuid.uuid4(), slug=permission_slug, display_name=permission_display, description=permission_description)
  permission_stmt = permission_stmt.on_conflict_do_update(index_elements=["slug"], set_={"display_name": permission_display, "description": permission_description})
  await session.execute(permission_stmt)
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


async def ensure_org_feature_flag_rows(session: AsyncSession, *, org_id: uuid.UUID) -> None:
  """Provision missing organization-feature rows so strict tenant chains remain deterministic."""
  # Load current feature definitions once so provisioning can insert only missing rows.
  flags_result = await session.execute(select(FeatureFlag.id, FeatureFlag.key))
  flags = [(row[0], str(row[1])) for row in flags_result.fetchall()]
  if not flags:
    return
  # Load already provisioned rows to avoid unnecessary writes.
  existing_result = await session.execute(select(OrganizationFeatureFlag.feature_flag_id).where(OrganizationFeatureFlag.org_id == org_id))
  existing_ids = {row[0] for row in existing_result.fetchall()}
  # Insert missing rows with strict defaults: permission flags enabled, product flags disabled.
  for flag_id, flag_key in flags:
    if flag_id in existing_ids:
      continue
    session.add(OrganizationFeatureFlag(org_id=org_id, feature_flag_id=flag_id, enabled=flag_key.startswith("perm.")))
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
  """Resolve effective feature flags with strict deny-by-default scope evaluation."""
  # Evaluate all known flags once to avoid per-flag database round-trips.
  decisions = await resolve_feature_flag_decisions(session, keys=None, org_id=org_id, subscription_tier_id=subscription_tier_id, user_id=user_id)
  return {key: bool(decision.enabled) for key, decision in decisions.items()}


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
  # Reuse strict evaluator so every caller shares the same deny-by-default behavior.
  normalized = validate_flag_key(key)
  decision = await resolve_feature_flag_decision(session, key=normalized, org_id=org_id, subscription_tier_id=subscription_tier_id, user_id=user_id)
  return bool(decision.enabled)


async def resolve_feature_flag_decision(session: AsyncSession, *, key: str, org_id: uuid.UUID | None, subscription_tier_id: int | None, user_id: uuid.UUID | None = None) -> FeatureFlagDecision:
  """Resolve strict decision metadata for a single feature flag key."""
  # Normalize input keys so downstream map lookups remain deterministic.
  normalized = validate_flag_key(key)
  decisions = await resolve_feature_flag_decisions(session, keys=[normalized], org_id=org_id, subscription_tier_id=subscription_tier_id, user_id=user_id)
  return decisions[normalized]


async def resolve_feature_flag_decisions(session: AsyncSession, *, keys: list[str] | None, org_id: uuid.UUID | None, subscription_tier_id: int | None, user_id: uuid.UUID | None = None) -> dict[str, FeatureFlagDecision]:
  """Resolve strict decision metadata for one or many feature flags."""
  # Normalize requested keys first so we can safely match DB rows and synthesize missing entries.
  requested_keys: list[str] | None = None
  if keys is not None:
    requested_keys = [validate_flag_key(value) for value in keys]

  # Load all candidate flag definitions in a single query to avoid N+1 behavior.
  flags_stmt = select(FeatureFlag)
  if requested_keys is not None:
    flags_stmt = flags_stmt.where(FeatureFlag.key.in_(requested_keys))
  flags_result = await session.execute(flags_stmt.order_by(FeatureFlag.key.asc()))
  flags = list(flags_result.scalars().all())
  flags_by_key = {flag.key: flag for flag in flags}

  # Resolve globally disabled runtime-config keys once per request.
  globally_disabled = await resolve_global_disabled_features(session)

  # Resolve whether this user context should follow tenant chain semantics.
  is_tenant_tier: bool | None = None
  if subscription_tier_id is not None:
    tier_stmt = select(SubscriptionTier.is_tenant_tier).where(SubscriptionTier.id == int(subscription_tier_id))
    tier_result = await session.execute(tier_stmt)
    row = tier_result.one_or_none()
    is_tenant_tier = bool(row[0]) if row is not None else None
  is_tenant_context = bool(org_id is not None and is_tenant_tier is True)

  # Load tier overrides for all relevant flags in one query.
  tier_map: dict[str, bool] = {}
  if subscription_tier_id is not None:
    tier_stmt = (
      select(FeatureFlag.key, SubscriptionTierFeatureFlag.enabled).join(SubscriptionTierFeatureFlag, SubscriptionTierFeatureFlag.feature_flag_id == FeatureFlag.id).where(SubscriptionTierFeatureFlag.subscription_tier_id == int(subscription_tier_id))
    )
    if requested_keys is not None:
      tier_stmt = tier_stmt.where(FeatureFlag.key.in_(requested_keys))
    tier_result = await session.execute(tier_stmt)
    tier_map = {str(key): bool(enabled) for key, enabled in tier_result.fetchall()}

  # Load tenant overrides for all relevant flags in one query.
  tenant_map: dict[str, bool] = {}
  if org_id is not None:
    tenant_stmt = select(FeatureFlag.key, OrganizationFeatureFlag.enabled).join(OrganizationFeatureFlag, OrganizationFeatureFlag.feature_flag_id == FeatureFlag.id).where(OrganizationFeatureFlag.org_id == org_id)
    if requested_keys is not None:
      tenant_stmt = tenant_stmt.where(FeatureFlag.key.in_(requested_keys))
    tenant_result = await session.execute(tenant_stmt)
    tenant_map = {str(key): bool(enabled) for key, enabled in tenant_result.fetchall()}

  # Load active promo overrides in one query for non-tenant fallback checks.
  promo_map: dict[str, bool] = {}
  if user_id is not None:
    promo_map = await list_active_user_feature_overrides(session, user_id=user_id)
    if requested_keys is not None:
      promo_map = {key: value for key, value in promo_map.items() if key in requested_keys}

  # Evaluate every requested/known key using strict scope chain semantics.
  ordered_keys = requested_keys if requested_keys is not None else sorted(flags_by_key.keys())
  decisions: dict[str, FeatureFlagDecision] = {}
  for key in ordered_keys:
    flag = flags_by_key.get(key)
    if flag is None:
      decisions[key] = FeatureFlagDecision(
        key=key,
        enabled=False,
        reason_code=FEATURE_REASON_MISCONFIGURED,
        global_enabled=False,
        tier_enabled=None,
        tier_record_exists=False,
        tenant_enabled=None,
        tenant_record_exists=False,
        promo_enabled=None,
        promo_record_exists=False,
        is_tenant_tier=is_tenant_tier,
        is_tenant_context=is_tenant_context,
        missing_scope="global",
      )
      continue

    # Evaluate global default and runtime kill-switch first so hard disables always win.
    global_enabled = bool(flag.default_enabled) and key not in globally_disabled
    if not global_enabled:
      decisions[key] = FeatureFlagDecision(
        key=key,
        enabled=False,
        reason_code=FEATURE_REASON_GLOBAL_DISABLED,
        global_enabled=False,
        tier_enabled=tier_map.get(key),
        tier_record_exists=key in tier_map,
        tenant_enabled=tenant_map.get(key),
        tenant_record_exists=key in tenant_map,
        promo_enabled=promo_map.get(key),
        promo_record_exists=key in promo_map,
        is_tenant_tier=is_tenant_tier,
        is_tenant_context=is_tenant_context,
      )
      continue

    # Reject contexts without a resolvable subscription tier as configuration errors.
    if subscription_tier_id is None or is_tenant_tier is None:
      decisions[key] = FeatureFlagDecision(
        key=key,
        enabled=False,
        reason_code=FEATURE_REASON_MISCONFIGURED,
        global_enabled=True,
        tier_enabled=tier_map.get(key),
        tier_record_exists=key in tier_map,
        tenant_enabled=tenant_map.get(key),
        tenant_record_exists=key in tenant_map,
        promo_enabled=promo_map.get(key),
        promo_record_exists=key in promo_map,
        is_tenant_tier=is_tenant_tier,
        is_tenant_context=is_tenant_context,
        missing_scope="tier",
      )
      continue

    # Apply tenant strict chain when the user is in a tenant tier and org context.
    if is_tenant_context:
      if key not in tier_map:
        decisions[key] = FeatureFlagDecision(
          key=key,
          enabled=False,
          reason_code=FEATURE_REASON_MISCONFIGURED,
          global_enabled=True,
          tier_enabled=None,
          tier_record_exists=False,
          tenant_enabled=tenant_map.get(key),
          tenant_record_exists=key in tenant_map,
          promo_enabled=promo_map.get(key),
          promo_record_exists=key in promo_map,
          is_tenant_tier=is_tenant_tier,
          is_tenant_context=True,
          missing_scope="tier",
        )
        continue
      if tier_map[key] is False:
        decisions[key] = FeatureFlagDecision(
          key=key,
          enabled=False,
          reason_code=FEATURE_REASON_TIER_DISABLED,
          global_enabled=True,
          tier_enabled=False,
          tier_record_exists=True,
          tenant_enabled=tenant_map.get(key),
          tenant_record_exists=key in tenant_map,
          promo_enabled=promo_map.get(key),
          promo_record_exists=key in promo_map,
          is_tenant_tier=is_tenant_tier,
          is_tenant_context=True,
        )
        continue
      if key not in tenant_map:
        decisions[key] = FeatureFlagDecision(
          key=key,
          enabled=False,
          reason_code=FEATURE_REASON_MISCONFIGURED,
          global_enabled=True,
          tier_enabled=True,
          tier_record_exists=True,
          tenant_enabled=None,
          tenant_record_exists=False,
          promo_enabled=promo_map.get(key),
          promo_record_exists=key in promo_map,
          is_tenant_tier=is_tenant_tier,
          is_tenant_context=True,
          missing_scope="tenant",
        )
        continue
      if tenant_map[key] is False:
        decisions[key] = FeatureFlagDecision(
          key=key,
          enabled=False,
          reason_code=FEATURE_REASON_TENANT_DISABLED,
          global_enabled=True,
          tier_enabled=True,
          tier_record_exists=True,
          tenant_enabled=False,
          tenant_record_exists=True,
          promo_enabled=promo_map.get(key),
          promo_record_exists=key in promo_map,
          is_tenant_tier=is_tenant_tier,
          is_tenant_context=True,
        )
        continue
      decisions[key] = FeatureFlagDecision(
        key=key,
        enabled=True,
        reason_code=None,
        global_enabled=True,
        tier_enabled=True,
        tier_record_exists=True,
        tenant_enabled=True,
        tenant_record_exists=True,
        promo_enabled=promo_map.get(key),
        promo_record_exists=key in promo_map,
        is_tenant_tier=is_tenant_tier,
        is_tenant_context=True,
      )
      continue

    # Apply non-tenant chain: tier first, then promo fallback if tier is disabled.
    if key not in tier_map:
      decisions[key] = FeatureFlagDecision(
        key=key,
        enabled=False,
        reason_code=FEATURE_REASON_MISCONFIGURED,
        global_enabled=True,
        tier_enabled=None,
        tier_record_exists=False,
        tenant_enabled=tenant_map.get(key),
        tenant_record_exists=key in tenant_map,
        promo_enabled=promo_map.get(key),
        promo_record_exists=key in promo_map,
        is_tenant_tier=is_tenant_tier,
        is_tenant_context=False,
        missing_scope="tier",
      )
      continue
    if tier_map[key] is True:
      decisions[key] = FeatureFlagDecision(
        key=key,
        enabled=True,
        reason_code=None,
        global_enabled=True,
        tier_enabled=True,
        tier_record_exists=True,
        tenant_enabled=tenant_map.get(key),
        tenant_record_exists=key in tenant_map,
        promo_enabled=promo_map.get(key),
        promo_record_exists=key in promo_map,
        is_tenant_tier=is_tenant_tier,
        is_tenant_context=False,
      )
      continue
    promo_enabled = promo_map.get(key)
    if promo_enabled is True:
      decisions[key] = FeatureFlagDecision(
        key=key,
        enabled=True,
        reason_code=None,
        global_enabled=True,
        tier_enabled=False,
        tier_record_exists=True,
        tenant_enabled=tenant_map.get(key),
        tenant_record_exists=key in tenant_map,
        promo_enabled=True,
        promo_record_exists=True,
        is_tenant_tier=is_tenant_tier,
        is_tenant_context=False,
      )
      continue
    decisions[key] = FeatureFlagDecision(
      key=key,
      enabled=False,
      reason_code=FEATURE_REASON_PROMO_DISABLED,
      global_enabled=True,
      tier_enabled=False,
      tier_record_exists=True,
      tenant_enabled=tenant_map.get(key),
      tenant_record_exists=key in tenant_map,
      promo_enabled=promo_enabled,
      promo_record_exists=key in promo_map,
      is_tenant_tier=is_tenant_tier,
      is_tenant_context=False,
    )

  return decisions
