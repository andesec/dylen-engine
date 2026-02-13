"""Switch planner and section-builder runtime model defaults from Pro to Flash."""

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


async def _ensure_columns(connection: AsyncConnection, *, table_name: str, columns: list[str]) -> bool:
  """Return True when all required columns exist on the table."""
  if not await _table_exists(connection, table_name=table_name):
    return False

  for column in columns:
    if not await _column_exists(connection, table_name=table_name, column_name=column):
      return False

  return True


async def seed(connection: AsyncConnection) -> None:
  """Update existing runtime-config rows from Gemini 2.5 Pro to Gemini 2.5 Flash."""
  runtime_ready = await _ensure_columns(connection, table_name="runtime_config_values", columns=["key", "value_json"])
  if not runtime_ready:
    return

  await connection.execute(
    text(
      """
      UPDATE runtime_config_values
      SET value_json = CAST(:flash_value AS jsonb)
      WHERE key IN ('ai.section_builder.model', 'ai.planner.model')
        AND value_json = CAST(:pro_value AS jsonb)
      """
    ),
    {"pro_value": '"gemini/gemini-2.5-pro"', "flash_value": '"gemini/gemini-2.5-flash"'},
  )
