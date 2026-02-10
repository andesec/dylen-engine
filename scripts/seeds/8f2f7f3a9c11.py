"""Backfill strict feature-gating metadata and tier/org flag matrices."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_NEW_PERMISSION_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
  ("research:use", "Use Research", "Run research discovery and synthesis."),
  ("writing:check", "Run Writing Check", "Run writing feedback checks."),
  ("ocr:extract", "Extract OCR Text", "Extract text from uploaded images."),
  ("fenster:view", "View Fenster Widget", "Read and render fenster widgets."),
)
_PRODUCT_FEATURE_DEFINITIONS: tuple[tuple[str, str], ...] = (("feature.research", "Enable research workflows."), ("feature.writing", "Enable writing checks."), ("feature.ocr", "Enable OCR extraction."), ("feature.fenster", "Enable fenster widgets."))
_FEATURE_TIER_ENABLEMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (("feature.research", ("Starter", "Plus", "Pro")), ("feature.writing", ("Starter", "Plus", "Pro")), ("feature.ocr", ("Starter", "Plus", "Pro")), ("feature.fenster", ("Plus", "Pro")))
_WRITING_CHECK_LIMITS_PER_TIER: tuple[tuple[str, int], ...] = (("Free", 0), ("Starter", 30), ("Plus", 120), ("Pro", 500))


async def _table_exists(connection: AsyncConnection, *, table_name: str, schema: str | None = None) -> bool:
  """Return True when a table exists in the target schema."""
  resolved_schema = schema or "public"
  result = await connection.execute(
    text(
      """
      SELECT 1
      FROM information_schema.tables
      WHERE table_schema = :schema
        AND table_name = :table_name
        AND table_type = 'BASE TABLE'
      LIMIT 1
      """
    ),
    {"schema": resolved_schema, "table_name": table_name},
  )
  return result.first() is not None


async def _column_exists(connection: AsyncConnection, *, table_name: str, column_name: str, schema: str | None = None) -> bool:
  """Return True when a column exists on the specified table."""
  resolved_schema = schema or "public"
  result = await connection.execute(
    text(
      """
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema = :schema
        AND table_name = :table_name
        AND column_name = :column_name
      LIMIT 1
      """
    ),
    {"schema": resolved_schema, "table_name": table_name, "column_name": column_name},
  )
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
  """Backfill strict feature-gating rows and route permissions idempotently."""
  # Keep seeded tier classification aligned with strict tenant resolution logic.
  if await _column_exists(connection, table_name="subscription_tiers", column_name="is_tenant_tier"):
    # Keep all tiers non-tenant until tenant-specific tiers are explicitly introduced.
    await connection.execute(text("UPDATE subscription_tiers SET is_tenant_tier = FALSE"))

  # Add newly introduced function-level permissions used by strict route gating.
  if await _ensure_columns(connection, table_name="permissions", columns=["id", "slug", "display_name", "description"]):
    for slug, display_name, description in _NEW_PERMISSION_DEFINITIONS:
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
        {"id": uuid.uuid4(), "slug": slug, "display_name": display_name, "description": description},
      )

  # Grant newly introduced permissions to default roles so existing users remain functional.
  if await _ensure_columns(connection, table_name="roles", columns=["id", "name"]) and await _ensure_columns(connection, table_name="role_permissions", columns=["role_id", "permission_id"]):
    role_rows = await connection.execute(text("SELECT id, name FROM roles WHERE name = ANY(:names)"), {"names": ["Super Admin", "Admin", "User", "Tenant_Admin", "Tenant_User"]})
    role_ids = {str(row[1]): row[0] for row in role_rows.fetchall()}
    permission_rows = await connection.execute(text("SELECT id, slug FROM permissions"))
    permission_ids = {str(row[1]): row[0] for row in permission_rows.fetchall()}
    for role_name in ["Admin", "User", "Tenant_Admin", "Tenant_User", "Super Admin"]:
      role_id = role_ids.get(role_name)
      if role_id is None:
        continue
      for slug, _display_name, _description in _NEW_PERMISSION_DEFINITIONS:
        permission_id = permission_ids.get(slug)
        if permission_id is None:
          continue
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

  # Ensure every permission has a strict permission-flag definition.
  if await _ensure_columns(connection, table_name="permissions", columns=["slug"]) and await _ensure_columns(connection, table_name="feature_flags", columns=["id", "key", "description", "default_enabled"]):
    # Backfill product feature flags so strict tier rows have canonical keys.
    for key, description in _PRODUCT_FEATURE_DEFINITIONS:
      await connection.execute(
        text(
          """
          INSERT INTO feature_flags (id, key, description, default_enabled)
          VALUES (:id, :key, :description, :default_enabled)
          ON CONFLICT (key) DO UPDATE
          SET description = EXCLUDED.description
          """
        ),
        {"id": uuid.uuid4(), "key": key, "description": description, "default_enabled": False},
      )
    # Keep permission feature flags present and enabled by default.
    permission_rows = await connection.execute(text("SELECT slug FROM permissions"))
    for row in permission_rows.fetchall():
      slug = str(row[0])
      await connection.execute(
        text(
          """
          INSERT INTO feature_flags (id, key, description, default_enabled)
          VALUES (:id, :key, :description, :default_enabled)
          ON CONFLICT (key) DO UPDATE
          SET description = EXCLUDED.description,
              default_enabled = EXCLUDED.default_enabled
          """
        ),
        {"id": uuid.uuid4(), "key": f"perm.{slug}", "description": f"Enable permission `{slug}`.", "default_enabled": True},
      )

  # Ensure strict tier rows exist for every flag and keep permission flags enabled by default.
  tier_matrix_ready = (
    await _ensure_columns(connection, table_name="subscription_tiers", columns=["id"])
    and await _ensure_columns(connection, table_name="feature_flags", columns=["id", "key"])
    and await _ensure_columns(connection, table_name="subscription_tier_feature_flags", columns=["subscription_tier_id", "feature_flag_id", "enabled"])
  )
  if tier_matrix_ready:
    await connection.execute(
      text(
        """
        INSERT INTO subscription_tier_feature_flags (subscription_tier_id, feature_flag_id, enabled)
        SELECT st.id, ff.id, CASE WHEN ff.key LIKE 'perm.%' THEN TRUE ELSE FALSE END
        FROM subscription_tiers st
        CROSS JOIN feature_flags ff
        ON CONFLICT (subscription_tier_id, feature_flag_id) DO NOTHING
        """
      )
    )
    # Turn on selected product features by tier so users gain capabilities through plan entitlements.
    tier_rows = await connection.execute(text("SELECT id, name FROM subscription_tiers"))
    tier_ids = {str(row[1]): int(row[0]) for row in tier_rows.fetchall()}
    flag_rows = await connection.execute(text("SELECT id, key FROM feature_flags"))
    flag_ids = {str(row[1]): row[0] for row in flag_rows.fetchall()}
    for flag_key, tier_names in _FEATURE_TIER_ENABLEMENTS:
      feature_flag_id = flag_ids.get(flag_key)
      if feature_flag_id is None:
        continue
      for tier_name in tier_names:
        subscription_tier_id = tier_ids.get(tier_name)
        if subscription_tier_id is None:
          continue
        await connection.execute(
          text(
            """
            INSERT INTO subscription_tier_feature_flags (subscription_tier_id, feature_flag_id, enabled)
            VALUES (:subscription_tier_id, :feature_flag_id, :enabled)
            ON CONFLICT (subscription_tier_id, feature_flag_id) DO UPDATE
            SET enabled = EXCLUDED.enabled
            """
          ),
          {"subscription_tier_id": subscription_tier_id, "feature_flag_id": feature_flag_id, "enabled": True},
        )
    await connection.execute(
      text(
        """
        UPDATE subscription_tier_feature_flags stff
        SET enabled = TRUE
        FROM feature_flags ff
        WHERE stff.feature_flag_id = ff.id
          AND ff.key LIKE 'perm.%'
        """
      )
    )

  # Ensure strict tenant rows exist for every org/flag and keep permission flags enabled.
  org_matrix_ready = (
    await _ensure_columns(connection, table_name="organizations", columns=["id"])
    and await _ensure_columns(connection, table_name="feature_flags", columns=["id", "key"])
    and await _ensure_columns(connection, table_name="organization_feature_flags", columns=["org_id", "feature_flag_id", "enabled"])
  )
  if org_matrix_ready:
    await connection.execute(
      text(
        """
        INSERT INTO organization_feature_flags (org_id, feature_flag_id, enabled)
        SELECT org.id, ff.id, CASE WHEN ff.key LIKE 'perm.%' THEN TRUE ELSE FALSE END
        FROM organizations org
        CROSS JOIN feature_flags ff
        ON CONFLICT (org_id, feature_flag_id) DO NOTHING
        """
      )
    )

  # Backfill writing-check quota limits so writing-capable tiers are not blocked by zero defaults.
  runtime_config_ready = await _ensure_columns(connection, table_name="subscription_tiers", columns=["id", "name"]) and await _ensure_columns(
    connection, table_name="runtime_config_values", columns=["id", "key", "scope", "subscription_tier_id", "value_json"]
  )
  if runtime_config_ready:
    tier_rows = await connection.execute(text("SELECT id, name FROM subscription_tiers"))
    tier_ids = {str(row[1]): int(row[0]) for row in tier_rows.fetchall()}
    for tier_name, writing_limit in _WRITING_CHECK_LIMITS_PER_TIER:
      subscription_tier_id = tier_ids.get(tier_name)
      if subscription_tier_id is None:
        continue
      await connection.execute(
        text(
          """
          INSERT INTO runtime_config_values (id, key, scope, subscription_tier_id, value_json)
          VALUES (:id, :key, :scope, :subscription_tier_id, CAST(:value_json AS jsonb))
          ON CONFLICT (key, subscription_tier_id) WHERE scope = 'TIER' DO UPDATE
          SET value_json = EXCLUDED.value_json
          """
        ),
        {"id": uuid.uuid4(), "key": "limits.writing_checks_per_month", "scope": "TIER", "subscription_tier_id": subscription_tier_id, "value_json": json.dumps(writing_limit)},
      )
    await connection.execute(
      text(
        """
        UPDATE organization_feature_flags off
        SET enabled = TRUE
        FROM feature_flags ff
        WHERE off.feature_flag_id = ff.id
          AND ff.key LIKE 'perm.%'
        """
      )
    )
