"""Seed data for migration a73c0f9a24a9 - add feature flag permissions."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

# Feature flag permission UUIDs - fixed for consistency
FEATURE_PERMISSIONS = {
  "feature_tutor_mode:use": uuid.UUID("33caeb8d-9824-4506-953a-c5e949db3dba"),
  "feature_tutor_active:use": uuid.UUID("34caeb8d-9824-4506-953a-c5e949db3dba"),
  "feature_mock_exams:use": uuid.UUID("35caeb8d-9824-4506-953a-c5e949db3dba"),
  "feature_mock_interviews:use": uuid.UUID("36caeb8d-9824-4506-953a-c5e949db3dba"),
  "feature_fenster:use": uuid.UUID("37caeb8d-9824-4506-953a-c5e949db3dba"),
  "feature_youtube_capture:use": uuid.UUID("38caeb8d-9824-4506-953a-c5e949db3dba"),
  "feature_image_generation:use": uuid.UUID("39caeb8d-9824-4506-953a-c5e949db3dba"),
  "feature_research:use": uuid.UUID("3acabeb8-9824-4506-953a-c5e949db3dba"),
  "feature_writing:use": uuid.UUID("3bcaeb8d-9824-4506-953a-c5e949db3dba"),
  "feature_ocr:use": uuid.UUID("3ccaeb8d-9824-4506-953a-c5e949db3dba"),
}

# Writing check limits per tier (matching backfill_feature_and_writing_quota_entitlements.py)
WRITING_CHECK_LIMITS_PER_TIER = {"Free": 0, "Starter": 30, "Plus": 120, "Pro": 500}


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
  """Add feature flag permissions to permissions table and assign to all user roles."""
  # Ensure permissions table exists
  if not await _ensure_columns(connection, table_name="permissions", columns=["id", "slug", "display_name", "description"]):
    return

  # Insert feature flag permissions
  permission_defs = [
    {"slug": "feature_tutor_mode:use", "display_name": "Use Tutor Mode", "description": "Use tutor mode features."},
    {"slug": "feature_tutor_active:use", "display_name": "Use Active Tutor", "description": "Use active tutor sessions."},
    {"slug": "feature_mock_exams:use", "display_name": "Use Mock Exams", "description": "Use mock exam features."},
    {"slug": "feature_mock_interviews:use", "display_name": "Use Mock Interviews", "description": "Use mock interview features."},
    {"slug": "feature_fenster:use", "display_name": "Use Fenster", "description": "Use Fenster widget features."},
    {"slug": "feature_youtube_capture:use", "display_name": "Use YouTube Capture", "description": "Use YouTube capture features."},
    {"slug": "feature_image_generation:use", "display_name": "Use Image Generation", "description": "Use image generation features."},
    {"slug": "feature_research:use", "display_name": "Use Research", "description": "Use research features."},
    {"slug": "feature_writing:use", "display_name": "Use Writing Check", "description": "Use writing check features."},
    {"slug": "feature_ocr:use", "display_name": "Use OCR", "description": "Use OCR features."},
  ]

  for perm_def in permission_defs:
    perm_id = FEATURE_PERMISSIONS.get(perm_def["slug"])
    if perm_id is None:
      continue
    await connection.execute(
      text(
        """
        INSERT INTO permissions (id, slug, display_name, description)
        VALUES (:id, :slug, :display_name, :description)
        ON CONFLICT (slug) DO UPDATE
        SET display_name = EXCLUDED.display_name,
            description = EXCLUDED.description
        """
      ),
      {"id": perm_id, "slug": perm_def["slug"], "display_name": perm_def["display_name"], "description": perm_def["description"]},
    )

  # Ensure role_permissions table exists
  if not await _ensure_columns(connection, table_name="role_permissions", columns=["role_id", "permission_id"]):
    return
  if not await _ensure_columns(connection, table_name="roles", columns=["id", "name"]):
    return

  # Assign feature permissions to all non-super-admin roles
  # (Super Admin already has all permissions via the baseline seed)
  role_names = ["Admin", "User", "Tenant_Admin", "Tenant_User"]

  for role_name in role_names:
    # Get role ID
    role_result = await connection.execute(text("SELECT id FROM roles WHERE name = :name LIMIT 1"), {"name": role_name})
    role_row = role_result.first()
    if role_row is None:
      continue
    role_id = role_row[0]

    # Assign all feature permissions to this role
    for permission_id in FEATURE_PERMISSIONS.values():
      await connection.execute(
        text(
          """
          INSERT INTO role_permissions (role_id, permission_id)
          VALUES (:role_id, :permission_id)
          ON CONFLICT (role_id, permission_id) DO NOTHING
          """
        ),
        {"role_id": role_id, "permission_id": permission_id},
      )

  # Also assign to Super Admin for completeness (even though it should already have all)
  super_admin_result = await connection.execute(text("SELECT id FROM roles WHERE name = 'Super Admin' LIMIT 1"))
  super_admin_row = super_admin_result.first()
  if super_admin_row is not None:
    super_admin_id = super_admin_row[0]
    for permission_id in FEATURE_PERMISSIONS.values():
      await connection.execute(
        text(
          """
          INSERT INTO role_permissions (role_id, permission_id)
          VALUES (:role_id, :permission_id)
          ON CONFLICT (role_id, permission_id) DO NOTHING
          """
        ),
        {"role_id": super_admin_id, "permission_id": permission_id},
      )

  # Add writing quota limits to runtime_config_values
  if not await _ensure_columns(connection, table_name="runtime_config_values", columns=["id", "key", "scope", "subscription_tier_id", "value_json"]):
    return
  if not await _ensure_columns(connection, table_name="subscription_tiers", columns=["id", "name"]):
    return

  # Get tier IDs
  tier_result = await connection.execute(text("SELECT id, name FROM subscription_tiers WHERE name = ANY(:tier_names)"), {"tier_names": list(WRITING_CHECK_LIMITS_PER_TIER.keys())})
  tier_rows = tier_result.fetchall()
  tier_ids = {row[1]: row[0] for row in tier_rows}

  # Insert writing check limits for each tier
  for tier_name, writing_limit in WRITING_CHECK_LIMITS_PER_TIER.items():
    tier_id = tier_ids.get(tier_name)
    if tier_id is None:
      continue
    stmt = text(
      """
      INSERT INTO runtime_config_values (id, key, scope, subscription_tier_id, value_json)
      VALUES (:id, :key, :scope, :subscription_tier_id, :value_json)
      ON CONFLICT (key, subscription_tier_id) WHERE scope = 'TIER' DO UPDATE
      SET value_json = EXCLUDED.value_json
      """
    )
    stmt = stmt.bindparams(bindparam("value_json", type_=JSONB))
    await connection.execute(stmt, {"id": uuid.uuid4(), "key": "limits.writing_checks_per_month", "scope": "TIER", "subscription_tier_id": tier_id, "value_json": json.dumps(writing_limit)})
