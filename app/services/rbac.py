"""RBAC helpers to keep authorization logic consistent across routes."""

from __future__ import annotations

import uuid

from app.schema.sql import Permission, Role, RoleLevel, RolePermission
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_MEMBER_ROLE_NAME = "Org Member"
DEFAULT_MEMBER_ROLE_DESCRIPTION = "Default role for new users."


async def get_role_by_id(session: AsyncSession, role_id: uuid.UUID) -> Role | None:
  """Fetch a role by id so authorization checks can validate assignments."""
  # Use direct lookup to keep permission checks fast.
  stmt = select(Role).where(Role.id == role_id)
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


async def get_role_by_name(session: AsyncSession, name: str) -> Role | None:
  """Fetch a role by name to support default assignments during onboarding."""
  # Look up roles by name for deterministic defaulting.
  stmt = select(Role).where(Role.name == name)
  result = await session.execute(stmt)
  return result.scalar_one_or_none()


async def get_or_create_role_by_name(session: AsyncSession, *, name: str, level: RoleLevel, description: str | None) -> Role:
  """Fetch a role by name and create it if missing so auth flows don't 500 on fresh DBs."""
  # Try to fetch first to avoid unnecessary writes in the common case.
  existing_role = await get_role_by_name(session, name)
  if existing_role is not None:
    return existing_role

  # Create the role; handle concurrent creation by re-fetching on unique violations.
  role = Role(name=name, level=level, description=description)
  session.add(role)
  try:
    await session.commit()
    await session.refresh(role)
    return role
  except IntegrityError:
    await session.rollback()
    concurrent_role = await get_role_by_name(session, name)
    if concurrent_role is None:
      raise
    return concurrent_role


async def get_or_create_default_member_role(session: AsyncSession) -> Role:
  """Ensure the default tenant member role exists for onboarding/signup flows."""
  # Keep defaults centralized so migrations and runtime enforcement stay aligned.
  return await get_or_create_role_by_name(session, name=DEFAULT_MEMBER_ROLE_NAME, level=RoleLevel.TENANT, description=DEFAULT_MEMBER_ROLE_DESCRIPTION)


async def list_roles(session: AsyncSession, *, limit: int, offset: int) -> tuple[list[Role], int]:
  """List roles for admin management workflows."""
  # Paginate roles for predictable response sizes.
  stmt = select(Role).limit(limit).offset(offset)
  result = await session.execute(stmt)
  roles = list(result.scalars().all())

  # Compute total for pagination metadata.
  count_stmt = select(func.count(Role.id))
  count_result = await session.execute(count_stmt)
  total = int(count_result.scalar_one())
  return roles, total


async def create_role(session: AsyncSession, *, name: str, level: RoleLevel, description: str | None) -> Role:
  """Create a role and persist it so RBAC assignments are durable."""
  # Create a new role row before returning to the caller.
  role = Role(name=name, level=level, description=description)
  session.add(role)
  await session.commit()
  await session.refresh(role)
  return role


async def list_permissions(session: AsyncSession) -> list[Permission]:
  """List permissions to help admins build role assignments."""
  # Keep permission listing simple to avoid unnecessary joins.
  stmt = select(Permission)
  result = await session.execute(stmt)
  return list(result.scalars().all())


async def get_permissions_by_ids(session: AsyncSession, permission_ids: list[uuid.UUID]) -> list[Permission]:
  """Fetch permissions by id so role assignments can be validated."""
  # Short-circuit on empty lists to reduce queries.
  if not permission_ids:
    return []

  # Fetch all permissions for the supplied ids.
  stmt = select(Permission).where(Permission.id.in_(permission_ids))
  result = await session.execute(stmt)
  return list(result.scalars().all())


async def set_role_permissions(session: AsyncSession, *, role: Role, permission_ids: list[uuid.UUID]) -> list[Permission]:
  """Replace role permissions so admin updates are idempotent."""
  # Validate permissions exist before modifying mappings.
  permissions = await get_permissions_by_ids(session, permission_ids)
  if len(permissions) != len(permission_ids):
    return []

  # Clear existing assignments before inserting the new set.
  await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
  # Insert the updated permission mappings for the role.
  session.add_all([RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions])
  await session.commit()
  return permissions


async def role_has_permission(session: AsyncSession, *, role_id: uuid.UUID, permission_slug: str) -> bool:
  """Check if a role has a permission slug for access control gates."""
  # Join role assignments to permissions for exact slug matching.
  stmt = select(Permission.id).join(RolePermission, Permission.id == RolePermission.permission_id).where(RolePermission.role_id == role_id, Permission.slug == permission_slug)
  result = await session.execute(stmt)
  return result.scalar_one_or_none() is not None


async def list_permission_slugs_for_role(session: AsyncSession, *, role_id: uuid.UUID) -> list[str]:
  """List permission slugs attached to a role for UI authorization hints."""
  # Load slugs in one query so clients can render without extra round trips.
  stmt = select(Permission.slug).join(RolePermission, Permission.id == RolePermission.permission_id).where(RolePermission.role_id == role_id).order_by(Permission.slug.asc())
  result = await session.execute(stmt)
  return [str(row[0]) for row in result.fetchall()]
