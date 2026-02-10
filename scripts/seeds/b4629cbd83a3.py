"""Grant all current permissions to the Super Admin role."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_SUPER_ADMIN_ROLE_NAME = "Super Admin"


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
  """Grant every permission row to Super Admin using idempotent upserts."""
  # Verify required RBAC tables and columns exist before granting permissions.
  roles_ready = await _ensure_columns(connection, table_name="roles", columns=["id", "name"])
  permissions_ready = await _ensure_columns(connection, table_name="permissions", columns=["id"])
  role_permissions_ready = await _ensure_columns(connection, table_name="role_permissions", columns=["role_id", "permission_id"])
  if not roles_ready or not permissions_ready or not role_permissions_ready:
    return

  # Resolve the Super Admin role ID and exit cleanly when the role is absent.
  role_result = await connection.execute(text("SELECT id FROM roles WHERE name = :role_name LIMIT 1"), {"role_name": _SUPER_ADMIN_ROLE_NAME})
  super_admin_role_id = role_result.scalar_one_or_none()
  if super_admin_role_id is None:
    return

  # Grant every existing permission to Super Admin without duplicating mappings.
  grant_all_permissions_statement = text(
    """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT :role_id, permissions.id
    FROM permissions
    ON CONFLICT (role_id, permission_id) DO NOTHING
    """
  )
  await connection.execute(grant_all_permissions_statement, {"role_id": super_admin_role_id})
