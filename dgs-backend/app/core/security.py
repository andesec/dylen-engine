from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.firebase import verify_id_token
from app.schema.sql import RoleLevel, User, UserStatus
from app.services.rbac import get_role_by_id, role_has_permission
from app.services.users import get_user_by_firebase_uid, get_user_tier_name, update_user_provider

security_scheme = HTTPBearer()


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


async def get_current_user(current_identity: tuple[User, dict[str, Any]] = Depends(get_current_identity)) -> User:  # noqa: B008
  """Return the current user model for handlers that don't need token claims."""
  # Return only the user object for existing dependency compatibility.
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

    return current_user

  return _dependency


def require_tier(allowed_tiers: list[str]):  # noqa: ANN001
  """Build a dependency that checks if user has one of the allowed tiers."""
  allowed_tiers_set = {t.lower() for t in allowed_tiers}

  async def _dependency(
    current_identity: tuple[User, dict[str, Any]] = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
  ) -> User:
    user, claims = current_identity
    # Check if user is active first
    if user.status != UserStatus.APPROVED:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

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
