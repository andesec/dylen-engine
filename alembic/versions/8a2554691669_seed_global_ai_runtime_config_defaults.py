"""seed runtime config defaults across global and tier scopes

Revision ID: 8a2554691669
Revises: 8f2f7f3a9c11
Create Date: 2026-02-11 05:30:11.072713

"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from app.config import get_settings
from app.core.migration_guards import table_exists
from app.schema.runtime_config import RuntimeConfigScope
from app.services.runtime_config import _env_fallback, list_runtime_config_definitions

# revision identifiers, used by Alembic.
revision: str = "8a2554691669"
down_revision: str | Sequence[str] | None = "8f2f7f3a9c11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scope_allowed(definition: Any, scope: RuntimeConfigScope) -> bool:
  """Check whether a config definition allows the target scope."""
  # Keep seeding aligned with runtime write rules.
  return scope in definition.allowed_scopes


def _load_tier_ids() -> list[int]:
  """Load all subscription tier IDs for tier-scope default seeding."""
  # Query IDs only so the migration remains schema-light.
  stmt = sa.text("SELECT id FROM subscription_tiers ORDER BY id")
  rows = op.get_bind().execute(stmt).fetchall()
  return [int(row[0]) for row in rows]


def _insert_global_if_missing(key: str, value: Any) -> None:
  """Insert a global config row only when no global row already exists."""
  # Preserve existing operator-set values by skipping conflicts.
  stmt = sa.text(
    """
    INSERT INTO runtime_config_values (id, key, scope, org_id, subscription_tier_id, user_id, value_json)
    VALUES (CAST(:id AS uuid), :key, 'GLOBAL', NULL, NULL, NULL, CAST(:value_json AS jsonb))
    ON CONFLICT (key) WHERE scope = 'GLOBAL'
    DO NOTHING
    """
  )
  payload = {"id": str(uuid.uuid4()), "key": key, "value_json": json.dumps(value)}
  op.get_bind().execute(stmt, payload)


def _insert_tier_if_missing(key: str, tier_id: int, value: Any) -> None:
  """Insert a tier config row only when no row exists for the key+tier pair."""
  # Preserve seeded/managed tier overrides by skipping conflicts.
  stmt = sa.text(
    """
    INSERT INTO runtime_config_values (id, key, scope, org_id, subscription_tier_id, user_id, value_json)
    VALUES (CAST(:id AS uuid), :key, 'TIER', NULL, :subscription_tier_id, NULL, CAST(:value_json AS jsonb))
    ON CONFLICT (key, subscription_tier_id) WHERE scope = 'TIER'
    DO NOTHING
    """
  )
  payload = {"id": str(uuid.uuid4()), "key": key, "subscription_tier_id": int(tier_id), "value_json": json.dumps(value)}
  op.get_bind().execute(stmt, payload)


def upgrade() -> None:
  """Seed missing runtime config defaults so Admin APIs can mutate concrete rows."""
  # Skip data writes when bootstrap schemas are partially applied.
  if not table_exists(table_name="runtime_config_values") or not table_exists(table_name="subscription_tiers"):
    return
  settings = get_settings()
  definitions = list_runtime_config_definitions()
  tier_ids = _load_tier_ids()
  for definition in definitions:
    # Derive each key default from the same env-backed fallback used at runtime.
    value = _env_fallback(settings, definition.key)
    if _scope_allowed(definition, RuntimeConfigScope.GLOBAL):
      _insert_global_if_missing(definition.key, value)
    if _scope_allowed(definition, RuntimeConfigScope.TIER):
      for tier_id in tier_ids:
        _insert_tier_if_missing(definition.key, tier_id, value)


def downgrade() -> None:
  """Keep seeded config rows to avoid deleting operator-managed runtime values."""
  # Intentionally no-op: seeded rows may have been edited in production.
  return
