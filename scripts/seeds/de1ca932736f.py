"""Backfill config/flags permissions and grant all permissions to Super Admin."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_SUPER_ADMIN_ROLE_NAME = "Super Admin"
_PERMISSION_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
  ("flags:read", "Read Feature Flags", "Read global feature flag definitions and effective values."),
  ("flags:write_global", "Write Global Feature Flags", "Create and update global feature flag defaults."),
  ("flags:write_tier", "Write Tier Feature Flags", "Set feature flag overrides at subscription tier scope."),
  ("flags:write_org", "Write Tenant Feature Flags", "Set feature flag overrides at tenant scope."),
  ("config:read", "Read Runtime Config", "Read runtime configuration definitions and scoped values."),
  ("config:write_global", "Write Global Runtime Config", "Update global runtime configuration values."),
  ("config:write_tier", "Write Tier Runtime Config", "Update tier-scoped runtime configuration values."),
  ("config:write_org", "Write Tenant Runtime Config", "Update tenant-scoped runtime configuration values."),
)


async def _table_exists(connection: AsyncConnection, *, table_name: str, schema: str | None = None) -> bool:
  """Return True when a table exists in the target schema."""
  # Default to the public schema when none is provided.
  resolved_schema = schema or "public"
  # Query information_schema to detect table presence safely.
  statement = text(
    """
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = :schema
      AND table_name = :table_name
      AND table_type = 'BASE TABLE'
    LIMIT 1
    """
  )
  result = await connection.execute(statement, {"schema": resolved_schema, "table_name": table_name})
  return result.first() is not None


async def _column_exists(connection: AsyncConnection, *, table_name: str, column_name: str, schema: str | None = None) -> bool:
  """Return True when a column exists on the specified table."""
  # Default to the public schema when none is provided.
  resolved_schema = schema or "public"
  # Query information_schema to detect column presence safely.
  statement = text(
    """
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = :schema
      AND table_name = :table_name
      AND column_name = :column_name
    LIMIT 1
    """
  )
  result = await connection.execute(statement, {"schema": resolved_schema, "table_name": table_name, "column_name": column_name})
  return result.first() is not None


async def _ensure_columns(connection: AsyncConnection, *, table_name: str, columns: list[str]) -> bool:
  """Return True when all required columns exist on the table."""
  # Ensure the table exists before checking columns.
  if not await _table_exists(connection, table_name=table_name):
    return False

  # Confirm each required column exists before running DML.
  for column in columns:
    if not await _column_exists(connection, table_name=table_name, column_name=column):
      return False

  return True


async def seed(connection: AsyncConnection) -> None:
  """Ensure required admin permission rows exist and are linked to Super Admin."""
  # Verify required RBAC tables and columns exist before any upserts.
  roles_ready = await _ensure_columns(connection, table_name="roles", columns=["id", "name"])
  permissions_ready = await _ensure_columns(connection, table_name="permissions", columns=["id", "slug", "display_name", "description"])
  role_permissions_ready = await _ensure_columns(connection, table_name="role_permissions", columns=["role_id", "permission_id"])
  if not roles_ready or not permissions_ready or not role_permissions_ready:
    return

  # Resolve the Super Admin role id and stop safely when it does not exist.
  role_result = await connection.execute(text("SELECT id FROM roles WHERE name = :role_name LIMIT 1"), {"role_name": _SUPER_ADMIN_ROLE_NAME})
  super_admin_role_id = role_result.scalar_one_or_none()
  if super_admin_role_id is None:
    return

  # Upsert required permission slugs used by runtime config and feature flag endpoints.
  upsert_permission_statement = text(
    """
    INSERT INTO permissions (id, slug, display_name, description)
    VALUES (:id, :slug, :display_name, :description)
    ON CONFLICT (slug) DO UPDATE
    SET display_name = EXCLUDED.display_name,
        description = EXCLUDED.description
    """
  )
  for slug, display_name, description in _PERMISSION_DEFINITIONS:
    await connection.execute(upsert_permission_statement, {"id": uuid.uuid4(), "slug": slug, "display_name": display_name, "description": description})

  # Grant every permission currently in the table to Super Admin without duplicate mappings.
  grant_all_permissions_statement = text(
    """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT :role_id, permissions.id
    FROM permissions
    ON CONFLICT (role_id, permission_id) DO NOTHING
    """
  )
  await connection.execute(grant_all_permissions_statement, {"role_id": super_admin_role_id})
