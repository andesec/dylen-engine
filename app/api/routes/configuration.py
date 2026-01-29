"""Admin endpoints for runtime configuration and feature flags."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.database import get_db
from app.core.security import require_permission
from app.schema.quotas import SubscriptionTier
from app.schema.runtime_config import RuntimeConfigScope
from app.schema.sql import RoleLevel, User
from app.services.feature_flags import create_feature_flag, get_feature_flag_by_key, list_feature_flags, resolve_effective_feature_flags, set_org_feature_flag, set_tier_feature_flag
from app.services.rbac import get_role_by_id
from app.services.runtime_config import get_runtime_config_definition, list_runtime_config_definitions, list_runtime_config_values, resolve_effective_runtime_config, upsert_runtime_config_value
from app.services.users import get_user_subscription_tier

router = APIRouter()

ConfigScopeLiteral = Literal["GLOBAL", "TIER", "TENANT"]
CONFIG_READ_DEP = Depends(require_permission("config:read"))
FLAGS_READ_DEP = Depends(require_permission("flags:read"))


class RuntimeConfigDefinitionRecord(BaseModel):
  key: str
  value_type: str
  description: str
  allowed_scopes: list[str]
  super_admin_only: bool


class RuntimeConfigSetRequest(BaseModel):
  key: str = Field(min_length=1)
  scope: ConfigScopeLiteral
  value: Any
  org_id: str | None = None
  tier_name: str | None = None


class FeatureFlagRecord(BaseModel):
  id: str
  key: str
  description: str | None
  default_enabled: bool


class FeatureFlagCreateRequest(BaseModel):
  key: str = Field(min_length=1)
  description: str | None = None
  default_enabled: bool = False


class FeatureFlagOverrideRequest(BaseModel):
  key: str = Field(min_length=1)
  enabled: bool
  org_id: str | None = None
  tier_name: str | None = None


def _definition_to_record(definition: Any) -> RuntimeConfigDefinitionRecord:
  """Map a runtime config definition into a stable response payload."""
  # Convert scope enums to strings so the client can render without schema coupling.
  scopes = [scope.value for scope in sorted(definition.allowed_scopes, key=lambda s: s.value)]
  return RuntimeConfigDefinitionRecord(key=definition.key, value_type=definition.value_type, description=definition.description, allowed_scopes=scopes, super_admin_only=definition.super_admin_only)


async def _require_global_role(db: AsyncSession, user: User) -> None:
  """Enforce GLOBAL role level when mutating global/tier settings."""
  # Load role metadata to check role level explicitly.
  role = await get_role_by_id(db, user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Requester role missing.")
  if role.level != RoleLevel.GLOBAL:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")


async def _require_tenant_scope(db: AsyncSession, user: User, target_org_id: uuid.UUID) -> None:
  """Enforce tenant scoping rules for org-level operations."""
  # Load role metadata to apply tenant scope restrictions.
  role = await get_role_by_id(db, user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Requester role missing.")
  if role.level == RoleLevel.TENANT:
    if user.org_id is None or user.org_id != target_org_id:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")


async def _resolve_tier_id(db: AsyncSession, tier_name: str) -> int:
  """Resolve subscription tier id by name."""
  # Normalize input to match seeded tier names.
  normalized = (tier_name or "").strip()
  if not normalized:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tier_name is required")
  result = await db.execute(select(SubscriptionTier).where(SubscriptionTier.name == normalized))
  tier = result.scalar_one_or_none()
  if tier is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
  return int(tier.id)


@router.get("/config/definitions", response_model=list[RuntimeConfigDefinitionRecord])
async def list_config_definitions(_current_user: User = CONFIG_READ_DEP) -> list[RuntimeConfigDefinitionRecord]:  # noqa: B008
  """List supported runtime configuration keys for admin UIs."""
  # Return allowlisted config definitions only.
  definitions = list_runtime_config_definitions()
  records: list[RuntimeConfigDefinitionRecord] = []
  for definition in definitions:
    records.append(_definition_to_record(definition))
  return records


@router.get("/config/values")
async def get_config_values(scope: ConfigScopeLiteral = Query("GLOBAL"), org_id: str | None = Query(None), tier_name: str | None = Query(None), current_user: User = CONFIG_READ_DEP, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """List explicitly set values for the requested config scope."""
  if scope == "GLOBAL":
    await _require_global_role(db, current_user)
    return await list_runtime_config_values(db, scope=RuntimeConfigScope.GLOBAL, org_id=None, subscription_tier_id=None)
  if scope == "TIER":
    await _require_global_role(db, current_user)
    if not tier_name:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tier_name is required for TIER scope")
    tier_id = await _resolve_tier_id(db, tier_name)
    return await list_runtime_config_values(db, scope=RuntimeConfigScope.TIER, org_id=None, subscription_tier_id=tier_id)
  if scope == "TENANT":
    if not org_id:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="org_id is required for TENANT scope")
    parsed_org_id = uuid.UUID(org_id)
    await _require_tenant_scope(db, current_user, parsed_org_id)
    return await list_runtime_config_values(db, scope=RuntimeConfigScope.TENANT, org_id=parsed_org_id, subscription_tier_id=None)
  raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid scope")


@router.put("/config/values", status_code=status.HTTP_200_OK)
async def set_config_value(request: RuntimeConfigSetRequest, current_user: User = CONFIG_READ_DEP, db: AsyncSession = Depends(get_db)) -> dict[str, str]:  # noqa: B008
  """Set a runtime config value for the requested scope."""
  # Validate key metadata before enforcing authorization rules.
  definition = get_runtime_config_definition(request.key)

  # Enforce super-admin-only keys by role name to avoid accidental exposure.
  if definition.super_admin_only:
    role = await get_role_by_id(db, current_user.role_id)
    if role is None or role.name != "Super Admin":
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

  if request.scope == "GLOBAL":
    await _require_global_role(db, current_user)
    _ = await require_permission("config:write_global")(current_user=current_user, db=db)  # type: ignore[misc]
    await upsert_runtime_config_value(db, key=definition.key, scope=RuntimeConfigScope.GLOBAL, value=request.value, org_id=None, subscription_tier_id=None)
    return {"status": "ok"}

  if request.scope == "TIER":
    await _require_global_role(db, current_user)
    _ = await require_permission("config:write_tier")(current_user=current_user, db=db)  # type: ignore[misc]
    if not request.tier_name:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tier_name is required for TIER scope")
    tier_id = await _resolve_tier_id(db, request.tier_name)
    await upsert_runtime_config_value(db, key=definition.key, scope=RuntimeConfigScope.TIER, value=request.value, org_id=None, subscription_tier_id=tier_id)
    return {"status": "ok"}

  if request.scope == "TENANT":
    _ = await require_permission("config:write_org")(current_user=current_user, db=db)  # type: ignore[misc]
    if not request.org_id:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="org_id is required for TENANT scope")
    parsed_org_id = uuid.UUID(request.org_id)
    await _require_tenant_scope(db, current_user, parsed_org_id)
    await upsert_runtime_config_value(db, key=definition.key, scope=RuntimeConfigScope.TENANT, value=request.value, org_id=parsed_org_id, subscription_tier_id=None)
    return {"status": "ok"}

  raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid scope")


@router.get("/config/effective")
async def get_effective_config(org_id: str | None = Query(None), current_user: User = CONFIG_READ_DEP, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """Return effective runtime config for a tenant context (admin helper endpoint)."""
  settings = get_settings()
  # Resolve tier context from the caller so tier-based defaults can be previewed.
  tier_id, tier_name = await get_user_subscription_tier(db, current_user.id)
  target_org_id = current_user.org_id
  if org_id:
    parsed = uuid.UUID(org_id)
    await _require_global_role(db, current_user)
    target_org_id = parsed
  effective = await resolve_effective_runtime_config(db, settings=settings, org_id=target_org_id, subscription_tier_id=tier_id)
  return {"tier": tier_name, "org_id": str(target_org_id) if target_org_id else None, "config": effective}


@router.get("/feature-flags", response_model=list[FeatureFlagRecord])
async def list_flags(_current_user: User = FLAGS_READ_DEP, db: AsyncSession = Depends(get_db)) -> list[FeatureFlagRecord]:  # noqa: B008
  """List all feature flag definitions."""
  flags = await list_feature_flags(db)
  return [FeatureFlagRecord(id=str(flag.id), key=flag.key, description=flag.description, default_enabled=bool(flag.default_enabled)) for flag in flags]


@router.post("/feature-flags", response_model=FeatureFlagRecord, dependencies=[Depends(require_permission("flags:write_global"))])
async def create_flag(request: FeatureFlagCreateRequest, current_user: User = Depends(require_permission("flags:write_global")), db: AsyncSession = Depends(get_db)) -> FeatureFlagRecord:  # noqa: B008
  """Create a new feature flag definition (global-only)."""
  await _require_global_role(db, current_user)
  flag = await create_feature_flag(db, key=request.key, description=request.description, default_enabled=request.default_enabled)
  return FeatureFlagRecord(id=str(flag.id), key=flag.key, description=flag.description, default_enabled=bool(flag.default_enabled))


@router.put("/feature-flags/override", status_code=status.HTTP_200_OK)
async def set_flag_override(request: FeatureFlagOverrideRequest, current_user: User = FLAGS_READ_DEP, db: AsyncSession = Depends(get_db)) -> dict[str, str]:  # noqa: B008
  """Set a tier or tenant override for a feature flag."""
  flag = await get_feature_flag_by_key(db, key=request.key)
  if flag is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature flag not found")

  if request.tier_name:
    _ = await require_permission("flags:write_tier")(current_user=current_user, db=db)  # type: ignore[misc]
    await _require_global_role(db, current_user)
    tier_id = await _resolve_tier_id(db, request.tier_name)
    await set_tier_feature_flag(db, subscription_tier_id=tier_id, feature_flag_id=flag.id, enabled=request.enabled)
    return {"status": "ok"}

  if request.org_id:
    _ = await require_permission("flags:write_org")(current_user=current_user, db=db)  # type: ignore[misc]
    parsed_org_id = uuid.UUID(request.org_id)
    await _require_tenant_scope(db, current_user, parsed_org_id)
    await set_org_feature_flag(db, org_id=parsed_org_id, feature_flag_id=flag.id, enabled=request.enabled)
    return {"status": "ok"}

  raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either org_id or tier_name is required")


@router.get("/feature-flags/effective")
async def get_effective_flags(org_id: str | None = Query(None), tier_name: str | None = Query(None), current_user: User = FLAGS_READ_DEP, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """Return effective feature flags for a tenant/tier context (admin helper endpoint)."""
  tier_id: int | None = None
  if tier_name:
    await _require_global_role(db, current_user)
    tier_id = await _resolve_tier_id(db, tier_name)
  else:
    tier_id, tier_name = await get_user_subscription_tier(db, current_user.id)

  target_org_id = current_user.org_id
  if org_id:
    parsed = uuid.UUID(org_id)
    await _require_tenant_scope(db, current_user, parsed)
    target_org_id = parsed

  effective = await resolve_effective_feature_flags(db, org_id=target_org_id, subscription_tier_id=tier_id)
  return {"tier": tier_name, "org_id": str(target_org_id) if target_org_id else None, "flags": effective}
