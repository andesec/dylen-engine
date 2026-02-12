import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_quota
from app.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user, require_permission
from app.schema.sql import User
from app.services.feature_flags import resolve_effective_feature_flags, resolve_feature_flag_decisions
from app.services.quotas import QuotaSummaryResponse, ResolvedQuota, build_quota_summary
from app.services.rbac import get_role_by_id, list_permission_slugs_for_role
from app.services.runtime_config import redact_super_admin_config, resolve_effective_runtime_config
from app.services.users import get_user_subscription_tier

router = APIRouter()


@router.get("/me", dependencies=[Depends(require_permission("user:self_read"))])
async def get_my_profile(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """
  Get the current user's profile.
  """
  # Fetch role metadata to return friendly profile details.
  role = await get_role_by_id(db, current_user.role_id)
  if role is None:
    return {"status": current_user.status, "role": None, "org_id": str(current_user.org_id) if current_user.org_id else None}

  return {"status": current_user.status, "role": {"id": str(role.id), "name": role.name, "level": role.level}, "org_id": str(current_user.org_id) if current_user.org_id else None}


@router.get("/me/quota", response_model=QuotaSummaryResponse, dependencies=[Depends(require_permission("user:quota_read"))])
async def get_my_quota(details: bool = False, quota: ResolvedQuota = Depends(get_quota)) -> QuotaSummaryResponse:  # noqa: B008
  """
  Get the current user's quota and subscription tier.
  """
  # Build the minimal quota response by default.
  summary = build_quota_summary(quota)
  # Attach full details only when explicitly requested.
  detailed_quota = quota if details else None

  return QuotaSummaryResponse(tier_name=quota.tier_name, quotas=summary, details=detailed_quota)


@router.get("/me/features", dependencies=[Depends(require_permission("user:features_read"))])
async def get_my_features(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """
  Get effective feature flags, runtime config, and permission hints for the current user.
  """
  # Resolve tier context so tier defaults apply to flags and config.
  tier_id, tier_name = await get_user_subscription_tier(db, current_user.id)

  # Compute effective feature flags so the UI can hide disabled capabilities.
  flags = await resolve_effective_feature_flags(db, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=current_user.id)
  decisions = await resolve_feature_flag_decisions(db, keys=None, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=current_user.id)

  # Resolve runtime config using env fallbacks plus DB overrides.
  settings = get_settings()
  runtime_config = await resolve_effective_runtime_config(db, settings=settings, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=None)
  runtime_config = redact_super_admin_config(runtime_config)

  # Return role permission slugs filtered by permission feature flags when defined.
  role = await get_role_by_id(db, current_user.role_id)
  permissions: list[str] = []
  functions: dict[str, dict[str, Any]] = {}
  if role is not None:
    permissions = await list_permission_slugs_for_role(db, role_id=role.id)
    perm_keys = [f"perm.{slug}" for slug in permissions]
    perm_decisions = await resolve_feature_flag_decisions(db, keys=perm_keys, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=current_user.id)
    filtered_permissions: list[str] = []
    for slug in permissions:
      perm_key = f"perm.{slug}"
      decision = perm_decisions[perm_key]
      if decision.enabled:
        filtered_permissions.append(slug)
      functions[slug] = {"enabled": bool(decision.enabled), "hidden": bool(not decision.enabled), "flag_key": perm_key, "reason_code": decision.reason_code}
    permissions = filtered_permissions

  # Expand feature metadata so clients can render robust hide/disable UX.
  feature_details: dict[str, dict[str, Any]] = {}
  for key, decision in decisions.items():
    feature_details[key] = {
      "enabled": bool(decision.enabled),
      "reason_code": decision.reason_code,
      "scopes": {
        "global_enabled": bool(decision.global_enabled),
        "tier_enabled": decision.tier_enabled,
        "tier_record_exists": bool(decision.tier_record_exists),
        "tenant_enabled": decision.tenant_enabled,
        "tenant_record_exists": bool(decision.tenant_record_exists),
        "promo_enabled": decision.promo_enabled,
        "promo_record_exists": bool(decision.promo_record_exists),
        "is_tenant_tier": decision.is_tenant_tier,
        "is_tenant_context": bool(decision.is_tenant_context),
        "missing_scope": decision.missing_scope,
      },
    }

  # Emit a stable version hash so UIs can cheaply detect capability changes.
  version_source = json.dumps({"flags": flags, "functions": functions, "permissions": permissions}, sort_keys=True, separators=(",", ":"))
  state_version = hashlib.sha256(version_source.encode("utf-8")).hexdigest()

  return {
    "tier": tier_name,
    "org_id": str(current_user.org_id) if current_user.org_id else None,
    "flags": flags,
    "features": feature_details,
    "functions": functions,
    "meta": {"tier": tier_name, "org_id": str(current_user.org_id) if current_user.org_id else None, "generated_at": datetime.now(UTC).isoformat(), "state_version": state_version},
    "config": runtime_config,
    "permissions": permissions,
  }
