"""Add runtime config values for research agent model configuration with Gemini 2.0 Flash defaults."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


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


async def _ensure_columns(connection: AsyncConnection, *, table_name: str, columns: list[str], schema: str | None = None) -> bool:
  """Return True when all required columns exist on the target table."""
  for column_name in columns:
    if not await _column_exists(connection, table_name=table_name, column_name=column_name, schema=schema):
      return False
  return True


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


async def run_seed(connection: AsyncConnection) -> None:
  """Add runtime config values for research agent models with Gemini 2.0 Flash defaults."""
  # Ensure schema readiness to avoid conflicts with concurrent migrations.
  if not await _table_exists(connection, table_name="runtime_config_values"):
    return

  # Ensure runtime_config_values table has required columns before proceeding.
  if not await _ensure_columns(connection, table_name="runtime_config_values", columns=["id", "key", "scope", "value_json"]):
    return

  # Add global defaults for research model configuration
  # Set ai.research.model to use gemini-2.0-flash-exp for synthesis
  await connection.execute(
    text(
      """
      INSERT INTO runtime_config_values (id, key, scope, org_id, subscription_tier_id, user_id, value_json)
      VALUES (:id, :key, 'GLOBAL', NULL, NULL, NULL, CAST(:value_json AS jsonb))
      ON CONFLICT (key, scope, COALESCE(org_id, '00000000-0000-0000-0000-000000000000'), COALESCE(subscription_tier_id, 0), COALESCE(user_id, '00000000-0000-0000-0000-000000000000')) 
      DO UPDATE SET value_json = EXCLUDED.value_json
      """
    ),
    {"id": uuid.uuid4(), "key": "ai.research.model", "value_json": json.dumps("gemini/gemini-2.0-flash-exp")},
  )

  # Set ai.research.router_model to use gemini-2.0-flash-exp for classification
  await connection.execute(
    text(
      """
      INSERT INTO runtime_config_values (id, key, scope, org_id, subscription_tier_id, user_id, value_json)
      VALUES (:id, :key, 'GLOBAL', NULL, NULL, NULL, CAST(:value_json AS jsonb))
      ON CONFLICT (key, scope, COALESCE(org_id, '00000000-0000-0000-0000-000000000000'), COALESCE(subscription_tier_id, 0), COALESCE(user_id, '00000000-0000-0000-0000-000000000000')) 
      DO UPDATE SET value_json = EXCLUDED.value_json
      """
    ),
    {"id": uuid.uuid4(), "key": "ai.research.router_model", "value_json": json.dumps("gemini/gemini-2.0-flash-exp")},
  )
