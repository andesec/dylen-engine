"""User CRUD helpers implemented with SQLAlchemy ORM.

This module centralizes how and why user records are created/updated so transport
layers (routes, auth dependencies, workers) don't duplicate query logic.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.schema.quotas import SubscriptionTier, UserUsageMetrics
from app.schema.sql import AuthMethod, User, UserStatus

logger = logging.getLogger(__name__)

async def get_user_by_firebase_uid(session: AsyncSession, firebase_uid: str) -> User | None:
  """Fetch a user by Firebase UID to support auth and session validation."""
  # Use a direct lookup to keep auth path predictable.
  stmt = select(User).where(User.firebase_uid == firebase_uid)
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
  """Fetch a user by primary key to support admin flows and background workers."""
  # Use primary-key lookup to keep admin flows fast.
  stmt = select(User).where(User.id == user_id)
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


def resolve_auth_method(provider: str | None) -> AuthMethod:
  """Resolve auth method from provider so RBAC status stays consistent with Firebase sign-in."""
  # Map Firebase provider identifiers into the enum used by RBAC.
  if provider in {"password", "email"}:
    return AuthMethod.NATIVE

  # Default to Google SSO until other providers are configured.
  return AuthMethod.GOOGLE_SSO


async def create_user(
  session: AsyncSession,
  *,
  firebase_uid: str,
  email: str,
  full_name: str | None,
  profession: str | None,
  city: str | None,
  country: str | None,
  age: int | None,
  photo_url: str | None,
  provider: str | None,
  role_id: uuid.UUID,
  org_id: uuid.UUID | None,
  status: UserStatus,
  auth_method: AuthMethod,
) -> User:
  """Create a new user row and commit it so downstream flows can rely on it."""
  # Persist the DB record before returning so callers can use the generated id.
  user = User(firebase_uid=firebase_uid, email=email, full_name=full_name, profession=profession, city=city, country=country, age=age, photo_url=photo_url, provider=provider, role_id=role_id, org_id=org_id, status=status, auth_method=auth_method)
  session.add(user)
  await session.commit()
  await session.refresh(user)
  await ensure_usage_row(session, user.id)
  return user


async def update_user_provider(session: AsyncSession, *, user: User, provider: str) -> User:
  """Update the auth provider to keep the local user record in sync with Firebase."""
  # Avoid unnecessary writes by checking for changes before committing.
  if user.provider == provider:
    return user

  # Update provider and derived auth method to match the IdP.
  user.provider = provider
  user.auth_method = resolve_auth_method(provider)
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def update_user_status(session: AsyncSession, *, user: User, status: UserStatus) -> User:
  """Update user status so access control reflects the latest admin decision."""
  # Skip writes when the status already matches the requested value.
  if user.status == status:
    return user

  # Persist status updates before notifying other systems.
  user.status = status
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def update_user_role(session: AsyncSession, *, user: User, role_id: uuid.UUID) -> User:
  """Update user role to align access with RBAC assignments."""
  # Avoid writes when role assignment is already current.
  if user.role_id == role_id:
    return user

  # Persist role changes before updating any downstream claims.
  user.role_id = role_id
  session.add(user)
  await session.commit()
  await session.refresh(user)
  return user


async def list_users(session: AsyncSession, *, org_id: uuid.UUID | None, limit: int, offset: int) -> tuple[list[User], int]:
  """List users with optional org scoping to support admin experiences."""
  # Build base query scoped by tenant when required.
  stmt = select(User)
  if org_id:
    stmt = stmt.where(User.org_id == org_id)

  # Apply pagination in the database for predictable performance.
  stmt = stmt.limit(limit).offset(offset)
  result = await session.execute(stmt)
  users = list(result.scalars().all())

  # Compute total using the same filter for pagination metadata.
  count_stmt = select(func.count(User.id))
  if org_id:
    count_stmt = count_stmt.where(User.org_id == org_id)

  count_result = await session.execute(count_stmt)
  total = int(count_result.scalar_one())
  return users, total


async def delete_user(session: AsyncSession, user_id: uuid.UUID) -> bool:
  """Delete a user and all associated data (via cascade) to support GDPR erasure."""
  user = await session.get(User, user_id)
  if not user:
    return False

  await session.delete(user)
  await session.commit()
  return True


async def ensure_usage_row(session: AsyncSession, user_id: uuid.UUID, *, tier_id: int | None = None) -> UserUsageMetrics:
  """Ensure a usage metrics row exists for the user using atomic UPSERT."""

  # Default to provided tier or 'Free' tier if not specified.
  if tier_id is None:
    tier_stmt = select(SubscriptionTier).where(SubscriptionTier.name == "Free")
    tier_result = await session.execute(tier_stmt)
    free_tier = tier_result.scalar_one_or_none()
    if not free_tier:
      # Critical configuration error: 'Free' tier must exist for account creation.
      logger.error("Default 'Free' subscription tier missing; run migrations to apply seed data. Run 'alembic upgrade head' to apply seed migrations.")
      raise RuntimeError("Default 'Free' subscription tier not available.")
    tier_id = free_tier.id

  # Use INSERT ... ON CONFLICT DO NOTHING for atomic consistency
  stmt = insert(UserUsageMetrics).values(user_id=user_id, subscription_tier_id=tier_id, files_uploaded_count=0, images_uploaded_count=0, sections_generated_count=0, research_usage_count=0).on_conflict_do_nothing(index_elements=["user_id"])

  await session.execute(stmt)
  await session.commit()

  # Fetch the row, which is now guaranteed to exist (either inserted or already there)
  return await session.get(UserUsageMetrics, user_id)
