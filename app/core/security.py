from __future__ import annotations

from typing import Annotated, Any

from app.core.database import get_db
from app.core.firebase import verify_id_token
from app.schema.sql import RoleLevel, User, UserStatus
from app.services.feature_flags import get_feature_flag_by_key, is_feature_enabled
from app.services.rbac import get_or_create_default_member_role, get_role_by_id, role_has_permission
from app.services.users import create_user, get_user_by_firebase_uid, get_user_subscription_tier, get_user_tier_name, resolve_auth_method, update_user_provider
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

security_scheme = HTTPBearer()


async def _provision_user_from_claims(db: AsyncSession, *, firebase_uid: str, decoded_claims: dict[str, Any], provider_id: str | None) -> User:
  """Provision a new user row from verified token claims for onboarding-first flows."""
  token_email = decoded_claims.get("email")
  if not token_email:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token missing email")
  # Ensure the default role exists so fresh DBs do not break onboarding flows.
  default_role = await get_or_create_default_member_role(db)
  full_name = decoded_claims.get("name")
  photo_url = decoded_claims.get("picture")
  # Normalize optional token claims and derived fields before persisting.
  normalized_full_name = str(full_name) if full_name else None
  normalized_photo_url = str(photo_url) if photo_url else None
  auth_method = resolve_auth_method(provider_id)
  user_create_kwargs = {
    "firebase_uid": firebase_uid,
    "email": str(token_email),
    "full_name": normalized_full_name,
    "profession": None,
    "city": None,
    "country": None,
    "age": None,
    "photo_url": normalized_photo_url,
    "provider": provider_id,
    "role_id": default_role.id,
    "org_id": None,
    "status": UserStatus.PENDING,
    "auth_method": auth_method,
  }
  user = await create_user(db, **user_create_kwargs)
  return user


async def get_current_identity(token: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)], db: AsyncSession = Depends(get_db)) -> tuple[User, dict[str, Any]]:  # noqa: B008
  """Verify Firebase ID token and hydrate a user record for downstream checks."""
  # Decode the bearer token so claims can be used for authorization hints.
  id_token = token.credentials
  decoded_claims = await run_in_threadpool(verify_id_token, id_token)

  if not decoded_claims:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials", headers={"WWW-Authenticate": "Bearer"})

  firebase_uid = decoded_claims.get("uid")
  provider_id = decoded_claims.get("firebase", {}).get("sign_in_provider")

  if not firebase_uid:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token claims")

  # Resolve the user from Postgres using ORM queries.
  user = await get_user_by_firebase_uid(db, firebase_uid)

  if not user:
    # User must explicitly sign up first.
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

  # Optional: Update provider if it changed or wasn't set (passive sync)
  if provider_id and user.provider != provider_id:
    await update_user_provider(db, user=user, provider=provider_id)

  return user, decoded_claims


async def get_current_identity_or_provision(token: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)], db: AsyncSession = Depends(get_db)) -> tuple[User, dict[str, Any]]:  # noqa: B008
  """Verify Firebase ID token and provision a user record when missing for onboarding flows."""
  # Decode the bearer token so claims can be used for authorization hints.
  id_token = token.credentials
  decoded_claims = await run_in_threadpool(verify_id_token, id_token)
  if not decoded_claims:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication credentials", headers={"WWW-Authenticate": "Bearer"})
  firebase_uid = decoded_claims.get("uid")
  provider_id = decoded_claims.get("firebase", {}).get("sign_in_provider")
  if not firebase_uid:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token claims")
  # Resolve the user from Postgres using ORM queries.
  user = await get_user_by_firebase_uid(db, firebase_uid)
  if not user:
    # Onboarding-first: create the user record once the token is verified.
    user = await _provision_user_from_claims(db, firebase_uid=firebase_uid, decoded_claims=decoded_claims, provider_id=provider_id)
  # Optional: Update provider if it changed or wasn't set (passive sync)
  if provider_id and user.provider != provider_id:
    await update_user_provider(db, user=user, provider=provider_id)
  return user, decoded_claims


async def get_current_user(current_identity: tuple[User, dict[str, Any]] = Depends(get_current_identity)) -> User:  # noqa: B008
  """Return the current user model for handlers that don't need token claims."""
  # Return only the user object for existing dependency compatibility.
  return current_identity[0]


async def get_current_user_or_provision(current_identity: tuple[User, dict[str, Any]] = Depends(get_current_identity_or_provision)) -> User:  # noqa: B008
  """Return the current user model, provisioning a record when missing for onboarding flows."""
  # Return only the user object so handlers stay consistent with `get_current_user`.
  return current_identity[0]


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:  # noqa: B008
  """Block inactive users so only approved accounts access protected routes."""
  # Enforce status guard for all approved-only endpoints.
  if current_user.status != UserStatus.APPROVED:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

  return current_user


async def get_current_admin_user(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> User:  # noqa: B008
  """Require admin permission for protected administrative routes."""
  # Validate admin permission against RBAC tables for consistency.
  has_permission = await role_has_permission(db, role_id=current_user.role_id, permission_slug="user:manage")
  if not has_permission:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

  return current_user


def require_permission(permission_slug: str):  # noqa: ANN001
  """Build a dependency that checks for a permission slug via RBAC."""

  async def _dependency(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> User:  # noqa: B008
    """Verify the user role includes the required permission before proceeding."""
    # Query RBAC mappings to ensure permission is attached to the user's role.
    has_permission = await role_has_permission(db, role_id=current_user.role_id, permission_slug=permission_slug)
    if not has_permission:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

    # Support feature-flagging permissions without changing RBAC role tables.
    permission_flag_key = f"perm.{permission_slug}"
    flag = await get_feature_flag_by_key(db, key=permission_flag_key)
    if flag is not None:
      tier_id, _tier_name = await get_user_subscription_tier(db, current_user.id)
      enabled = await is_feature_enabled(db, key=permission_flag_key, org_id=current_user.org_id, subscription_tier_id=tier_id)
      if not enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission disabled")

    return current_user

  return _dependency


def require_feature_flag(flag_key: str):  # noqa: ANN001
  """Build a dependency that blocks requests when a feature flag is disabled."""

  async def _dependency(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> User:  # noqa: B008
    """Resolve the flag for the current tenant/tier and enforce it."""
    # Enforce secure defaults by treating missing flags as disabled.
    tier_id, _tier_name = await get_user_subscription_tier(db, current_user.id)
    enabled = await is_feature_enabled(db, key=flag_key, org_id=current_user.org_id, subscription_tier_id=tier_id)
    if not enabled:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "FEATURE_DISABLED", "flag": flag_key})
    return current_user

  return _dependency


def require_tier(allowed_tiers: list[str]):  # noqa: ANN001
  """Build a dependency that checks if user has one of the allowed tiers."""
  allowed_tiers_set = {t.lower() for t in allowed_tiers}

  async def _dependency(current_identity: tuple[User, dict[str, Any]] = Depends(get_current_identity), db: AsyncSession = Depends(get_db)) -> User:
    user, claims = current_identity
    # Check if user is active first
    if user.status != UserStatus.APPROVED:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "INACTIVE_USER", "detail": "Inactive user"})

    tier = claims.get("tier")

    if not tier:
      # Fallback to DB
      tier = await get_user_tier_name(db, user.id)

    if tier.lower() not in allowed_tiers_set:
      # Return specific error payload as per spec
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "UPGRADE_REQUIRED", "min_tier": allowed_tiers[0].lower()})

    return user

  return _dependency


def require_role_level(level: RoleLevel):  # noqa: ANN001
  """Build a dependency that checks role level for high-trust operations."""

  async def _dependency(current_user: User = Depends(get_current_active_user), db: AsyncSession = Depends(get_db)) -> User:  # noqa: B008
    """Confirm the user has a role at the required scope."""
    # Load role records to verify level for global vs tenant access.
    role = await get_role_by_id(db, current_user.role_id)
    if role is None or role.level != level:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")

    return current_user

  return _dependency
