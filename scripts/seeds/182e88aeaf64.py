"""Seed data for migration 182e88aeaf64."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def _table_exists(connection: AsyncConnection, *, table_name: str, schema: str | None = None) -> bool:
  """Return True when a table exists in the target schema."""
  resolved_schema = schema or "public"
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
  resolved_schema = schema or "public"
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


async def _ensure_columns(connection: AsyncConnection, *, table_name: str, columns: list[str] | tuple[str, ...]) -> bool:
  """Return True when all required columns exist on the table."""
  if not await _table_exists(connection, table_name=table_name):
    return False

  for column in columns:
    if not await _column_exists(connection, table_name=table_name, column_name=column):
      return False

  return True


async def seed(connection: AsyncConnection) -> None:
  """Restrict job and data-transfer permissions to Super Admin only."""
  if not await _ensure_columns(connection, table_name="roles", columns=["id", "name"]):
    return
  if not await _ensure_columns(connection, table_name="permissions", columns=["id", "slug"]):
    return
  if not await _ensure_columns(connection, table_name="role_permissions", columns=["role_id", "permission_id"]):
    return

  # Remove these permissions from all non-super-admin roles.
  await connection.execute(
    text(
      """
      DELETE FROM role_permissions rp
      USING permissions p
      WHERE rp.permission_id = p.id
        AND p.slug = ANY(:permission_slugs)
        AND rp.role_id <> (SELECT id FROM roles WHERE name = 'Super Admin' LIMIT 1)
      """
    ),
    {
      "permission_slugs": [
        "lesson:job_create",
        "job:create_own",
        "job:view_own",
        "job:retry_own",
        "job:cancel_own",
        "admin:jobs_read",
        "data_transfer:export_create",
        "data_transfer:export_read",
        "data_transfer:download_link_create",
        "data_transfer:hydrate_create",
        "data_transfer:hydrate_read",
      ]
    },
  )
