"""Seed runtime config defaults for global and tier scopes."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.config import get_settings
from app.schema.runtime_config import RuntimeConfigScope
from app.services.runtime_config import _env_fallback, list_runtime_config_definitions
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_REQUIRED_RUNTIME_CONFIG_COLUMNS: tuple[str, ...] = ("id", "key", "scope", "org_id", "subscription_tier_id", "user_id", "value_json")


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


async def _ensure_columns(connection: AsyncConnection, *, table_name: str, columns: tuple[str, ...]) -> bool:
  """Return True when all required columns exist on the table."""
  # Ensure the table exists before checking columns.
  if not await _table_exists(connection, table_name=table_name):
    return False

  # Confirm each required column exists before running DML.
  for column in columns:
    if not await _column_exists(connection, table_name=table_name, column_name=column):
      return False

  return True


async def _load_tier_ids(connection: AsyncConnection) -> list[int]:
  """Load all subscription tier IDs for tier-scope seeding."""
  # Query IDs only so the seed remains schema-light.
  result = await connection.execute(text("SELECT id FROM subscription_tiers ORDER BY id"))
  return [int(row[0]) for row in result.fetchall()]


async def _fetch_global_value(connection: AsyncConnection, *, key: str) -> Any:
  """Fetch an existing global config value when present."""
  # Look up an existing global row to avoid overwriting operator-managed values.
  result = await connection.execute(text("SELECT value_json FROM runtime_config_values WHERE key = :key AND scope = 'GLOBAL' LIMIT 1"), {"key": key})
  row = result.first()
  if row is None:
    return None

  return row[0]


async def _fetch_tier_value(connection: AsyncConnection, *, key: str, tier_id: int) -> Any:
  """Fetch an existing tier config value when present."""
  # Look up an existing tier row to avoid overwriting operator-managed values.
  result = await connection.execute(text("SELECT value_json FROM runtime_config_values WHERE key = :key AND scope = 'TIER' AND subscription_tier_id = :tier_id LIMIT 1"), {"key": key, "tier_id": tier_id})
  row = result.first()
  if row is None:
    return None

  return row[0]


async def _insert_global(connection: AsyncConnection, *, key: str, value: Any) -> None:
  """Insert a global config row when missing."""
  # Insert only when the row is missing to keep operator overrides intact.
  await connection.execute(
    text(
      """
      INSERT INTO runtime_config_values (id, key, scope, org_id, subscription_tier_id, user_id, value_json)
      VALUES (CAST(:id AS uuid), :key, 'GLOBAL', NULL, NULL, NULL, CAST(:value_json AS jsonb))
      ON CONFLICT (key) WHERE scope = 'GLOBAL'
      DO NOTHING
      """
    ),
    {"id": str(uuid.uuid4()), "key": key, "value_json": json.dumps(value)},
  )


async def _insert_tier(connection: AsyncConnection, *, key: str, tier_id: int, value: Any) -> None:
  """Insert a tier config row when missing."""
  # Insert only when the row is missing to keep operator overrides intact.
  await connection.execute(
    text(
      """
      INSERT INTO runtime_config_values (id, key, scope, org_id, subscription_tier_id, user_id, value_json)
      VALUES (CAST(:id AS uuid), :key, 'TIER', NULL, :subscription_tier_id, NULL, CAST(:value_json AS jsonb))
      ON CONFLICT (key, subscription_tier_id) WHERE scope = 'TIER'
      DO NOTHING
      """
    ),
    {"id": str(uuid.uuid4()), "key": key, "subscription_tier_id": int(tier_id), "value_json": json.dumps(value)},
  )


async def seed(connection: AsyncConnection) -> None:
  """Seed runtime config defaults for global and tier scopes."""
  # Ensure runtime config schema is available before seeding.
  runtime_ready = await _ensure_columns(connection, table_name="runtime_config_values", columns=_REQUIRED_RUNTIME_CONFIG_COLUMNS)
  if not runtime_ready:
    return

  # Ensure subscription tiers exist before seeding tier-scoped values.
  if not await _table_exists(connection, table_name="subscription_tiers"):
    return

  settings = get_settings()
  tier_ids = await _load_tier_ids(connection)
  definitions = list_runtime_config_definitions()
  for definition in definitions:
    value = _env_fallback(settings, definition.key)
    if RuntimeConfigScope.GLOBAL in definition.allowed_scopes:
      existing_value = await _fetch_global_value(connection, key=definition.key)
      if existing_value is None:
        await _insert_global(connection, key=definition.key, value=value)

    if RuntimeConfigScope.TIER in definition.allowed_scopes:
      for tier_id in tier_ids:
        existing_value = await _fetch_tier_value(connection, key=definition.key, tier_id=tier_id)
        if existing_value is None:
          await _insert_tier(connection, key=definition.key, tier_id=tier_id, value=value)
