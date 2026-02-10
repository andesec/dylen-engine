from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_quota
from app.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user, require_permission
from app.schema.sql import User
from app.services.feature_flags import resolve_effective_feature_flags, resolve_global_disabled_features
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
  disabled_keys = await resolve_global_disabled_features(db)
  for key in disabled_keys:
    flags.pop(key, None)

  # Resolve runtime config using env fallbacks plus DB overrides.
  settings = get_settings()
  runtime_config = await resolve_effective_runtime_config(db, settings=settings, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=None)
  runtime_config = redact_super_admin_config(runtime_config)

  # Return role permission slugs filtered by permission feature flags when defined.
  role = await get_role_by_id(db, current_user.role_id)
  permissions: list[str] = []
  if role is not None:
    permissions = await list_permission_slugs_for_role(db, role_id=role.id)
    filtered: list[str] = []
    for slug in permissions:
      # Only enforce permission flags when explicitly defined.
      if flags.get(f"perm.{slug}") is False:
        continue
      filtered.append(slug)
    permissions = filtered

  return {"tier": tier_name, "org_id": str(current_user.org_id) if current_user.org_id else None, "flags": flags, "config": runtime_config, "permissions": permissions}
