"""Seed tutor mode feature flags."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_MODE_FLAG_DEFINITIONS: tuple[tuple[str, str, bool], ...] = (("feature.tutor.mode", "Enable tutor mode.", False),)


async def _table_exists(connection: AsyncConnection, *, table_name: str, schema: str | None = None) -> bool:
  """Return True when a table exists in the target schema."""
  # Default to public schema when none is provided.
  resolved_schema = schema or "public"
  # Query information_schema to detect table presence.
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
  # Default to public schema when none is provided.
  resolved_schema = schema or "public"
  # Query information_schema to detect column presence.
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
  """Upsert tutor mode feature flags with secure defaults."""
  # Verify required columns before upserting feature flags.
  feature_flags_ready = await _ensure_columns(connection, table_name="feature_flags", columns=["id", "key", "description", "default_enabled"])
  if not feature_flags_ready:
    return

  # Insert or update mode flags so environments remain consistent across deploys.
  upsert_flag_statement = text(
    """
    INSERT INTO feature_flags (id, key, description, default_enabled)
    VALUES (:id, :key, :description, :default_enabled)
    ON CONFLICT (key) DO UPDATE
    SET description = EXCLUDED.description,
        default_enabled = EXCLUDED.default_enabled
    """
  )
  for key, description, default_enabled in _MODE_FLAG_DEFINITIONS:
    await connection.execute(upsert_flag_statement, {"id": uuid.uuid4(), "key": key, "description": description, "default_enabled": default_enabled})
