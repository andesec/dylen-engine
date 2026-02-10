"""Seed core RBAC and subscription tiers for the baseline migration."""

from __future__ import annotations

import uuid

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection


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
  """Insert required RBAC roles, permissions, and subscription tiers."""
  # Use fixed UUIDs so environments stay consistent after local resets.
  role_super_admin_id = uuid.UUID("3e56ebfc-1d62-42cb-a920-ab6e916e58bf")
  role_org_admin_id = uuid.UUID("102d6fab-322c-48f8-a8f8-0d9e5eb52aa6")
  role_org_member_id = uuid.UUID("d028adea-31a6-48fb-afd8-777a4cd410b4")
  permission_user_manage_id = uuid.UUID("2fcaeb8d-9824-4506-953a-c5e949db3db8")

  # Seed roles when the table and required columns exist.
  if await _ensure_columns(connection, table_name="roles", columns=["id", "name", "level", "description"]):
    await connection.execute(
      text(
        """
        INSERT INTO roles (id, name, level, description)
        VALUES
          (:id1, :name1, :level1, :desc1),
          (:id2, :name2, :level2, :desc2),
          (:id3, :name3, :level3, :desc3)
        ON CONFLICT (name) DO UPDATE
        SET level = EXCLUDED.level,
            description = EXCLUDED.description
        """
      ),
      {
        "id1": role_super_admin_id,
        "name1": "Super Admin",
        "level1": "GLOBAL",
        "desc1": "Global administrator.",
        "id2": role_org_admin_id,
        "name2": "Tenant_Admin",
        "level2": "TENANT",
        "desc2": "Organization administrator.",
        "id3": role_org_member_id,
        "name3": "Tenant_User",
        "level3": "TENANT",
        "desc3": "Default role for new users.",
      },
    )

  # Seed permissions when the table and required columns exist.
  if await _ensure_columns(connection, table_name="permissions", columns=["id", "slug", "display_name", "description"]):
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
      {"id": permission_user_manage_id, "slug": "user:manage", "display_name": "Manage Users", "description": "List users and update roles/statuses."},
    )

  # Seed role-permission mapping when the table and required columns exist.
  if await _ensure_columns(connection, table_name="role_permissions", columns=["role_id", "permission_id"]):
    await connection.execute(
      text(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        VALUES (:role_id, :permission_id)
        ON CONFLICT (role_id, permission_id) DO NOTHING
        """
      ),
      {"role_id": role_super_admin_id, "permission_id": permission_user_manage_id},
    )

  # Seed subscription tiers when the table and required columns exist.
  if await _ensure_columns(
    connection,
    table_name="subscription_tiers",
    columns=["name", "max_file_upload_kb", "highest_lesson_depth", "max_sections_per_lesson", "file_upload_quota", "image_upload_quota", "gen_sections_quota", "research_quota", "tutor_mode_enabled", "tutor_voice_tier"],
  ):
    await connection.execute(
      text(
        """
        INSERT INTO subscription_tiers (
          name,
          max_file_upload_kb,
          highest_lesson_depth,
          max_sections_per_lesson,
          file_upload_quota,
          image_upload_quota,
          gen_sections_quota,
          research_quota,
          tutor_mode_enabled,
          tutor_voice_tier
        )
        VALUES
          (:name1, :mfu1, :depth1, :sections1, :fuq1, :iuq1, :gsq1, :rq1, :tutor1, :voice1),
          (:name2, :mfu2, :depth2, :sections2, :fuq2, :iuq2, :gsq2, :rq2, :tutor2, :voice2),
          (:name3, :mfu3, :depth3, :sections3, :fuq3, :iuq3, :gsq3, :rq3, :tutor3, :voice3),
          (:name4, :mfu4, :depth4, :sections4, :fuq4, :iuq4, :gsq4, :rq4, :tutor4, :voice4)
        ON CONFLICT (name) DO UPDATE
        SET max_file_upload_kb = EXCLUDED.max_file_upload_kb,
            highest_lesson_depth = EXCLUDED.highest_lesson_depth,
            max_sections_per_lesson = EXCLUDED.max_sections_per_lesson,
            file_upload_quota = EXCLUDED.file_upload_quota,
            image_upload_quota = EXCLUDED.image_upload_quota,
            gen_sections_quota = EXCLUDED.gen_sections_quota,
            research_quota = EXCLUDED.research_quota,
            tutor_mode_enabled = EXCLUDED.tutor_mode_enabled,
            tutor_voice_tier = EXCLUDED.tutor_voice_tier
        """
      ),
      {
        "name1": "Free",
        "mfu1": 0,
        "depth1": "highlights",
        "sections1": 2,
        "fuq1": 0,
        "iuq1": 0,
        "gsq1": 10,
        "rq1": None,
        "tutor1": False,
        "voice1": "none",
        "name2": "Starter",
        "mfu2": 1024,
        "depth2": "detailed",
        "sections2": 6,
        "fuq2": 10,
        "iuq2": 10,
        "gsq2": 70,
        "rq2": None,
        "tutor2": False,
        "voice2": "none",
        "name3": "Plus",
        "mfu3": 2048,
        "depth3": "detailed",
        "sections3": 6,
        "fuq3": 40,
        "iuq3": 40,
        "gsq3": 150,
        "rq3": None,
        "tutor3": True,
        "voice3": "device",
        "name4": "Pro",
        "mfu4": 5120,
        "depth4": "training",
        "sections4": 10,
        "fuq4": 100,
        "iuq4": 100,
        "gsq4": 500,
        "rq4": None,
        "tutor4": True,
        "voice4": "premium",
      },
    )

  # Load subscription tier IDs to reuse across tier-scoped seed data.
  tier_names = ["Free", "Starter", "Plus", "Pro"]
  tier_result = await connection.execute(text("SELECT id, name FROM subscription_tiers WHERE name = ANY(:names)"), {"names": tier_names})
  tier_rows = tier_result.fetchall()
  tier_ids = {row[1]: row[0] for row in tier_rows}

  # Seed feature flags when the table and required columns exist.
  if await _ensure_columns(connection, table_name="feature_flags", columns=["id", "key", "description", "default_enabled"]):
    flag_defs = [
      {"id": uuid.uuid4(), "key": "feature.tutor.active", "description": "Enable active tutor sessions.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.mock_exams", "description": "Enable mock exams.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.mock_interviews", "description": "Enable mock interviews.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.fenster", "description": "Enable Fenster widgets.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.youtube_capture", "description": "Enable YouTube capture.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.image_generation", "description": "Enable image generation.", "default_enabled": False},
    ]
    for flag in flag_defs:
      # Upsert feature flags to keep keys stable across environments.
      upsert_flags_sql = "INSERT INTO feature_flags (id, key, description, default_enabled) VALUES (:id, :key, :description, :default_enabled) ON CONFLICT (key) DO UPDATE SET description = EXCLUDED.description, default_enabled = EXCLUDED.default_enabled"
      await connection.execute(text(upsert_flags_sql), flag)

  # Seed per-tier feature flag defaults when required tables and tiers exist.
  if await _ensure_columns(connection, table_name="subscription_tier_feature_flags", columns=["subscription_tier_id", "feature_flag_id", "enabled"]) and tier_ids:
    flag_keys = ["feature.tutor.active", "feature.mock_exams", "feature.mock_interviews", "feature.fenster", "feature.youtube_capture", "feature.image_generation"]
    flag_result = await connection.execute(text("SELECT id, key FROM feature_flags WHERE key = ANY(:keys)"), {"keys": flag_keys})
    flag_rows = flag_result.fetchall()
    flag_ids = {row[1]: row[0] for row in flag_rows}
    flag_assignments = [
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": flag_ids.get("feature.tutor.active"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Starter"), "feature_flag_id": flag_ids.get("feature.mock_exams"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": flag_ids.get("feature.mock_exams"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": flag_ids.get("feature.mock_exams"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": flag_ids.get("feature.mock_interviews"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": flag_ids.get("feature.mock_interviews"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": flag_ids.get("feature.fenster"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": flag_ids.get("feature.fenster"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Starter"), "feature_flag_id": flag_ids.get("feature.youtube_capture"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": flag_ids.get("feature.youtube_capture"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": flag_ids.get("feature.youtube_capture"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Starter"), "feature_flag_id": flag_ids.get("feature.image_generation"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": flag_ids.get("feature.image_generation"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": flag_ids.get("feature.image_generation"), "enabled": True},
    ]
    for assignment in flag_assignments:
      # Skip incomplete assignments when tiers or flags are missing.
      if assignment["subscription_tier_id"] is None or assignment["feature_flag_id"] is None:
        continue
      upsert_tier_flag_sql = (
        "INSERT INTO subscription_tier_feature_flags (subscription_tier_id, feature_flag_id, enabled) VALUES (:subscription_tier_id, :feature_flag_id, :enabled) ON CONFLICT (subscription_tier_id, feature_flag_id) DO UPDATE SET enabled = EXCLUDED.enabled"
      )
      await connection.execute(text(upsert_tier_flag_sql), assignment)

  # Seed tier-scoped runtime config values when the table and required columns exist.
  if await _ensure_columns(connection, table_name="runtime_config_values", columns=["id", "key", "scope", "subscription_tier_id", "value_json"]) and tier_ids:
    runtime_entries = [
      {"id": uuid.uuid4(), "key": "limits.lessons_per_week", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 3},
      {"id": uuid.uuid4(), "key": "limits.lessons_per_week", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 15},
      {"id": uuid.uuid4(), "key": "limits.lessons_per_week", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 30},
      {"id": uuid.uuid4(), "key": "limits.lessons_per_week", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 80},
      {"id": uuid.uuid4(), "key": "limits.sections_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 10},
      {"id": uuid.uuid4(), "key": "limits.sections_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 70},
      {"id": uuid.uuid4(), "key": "limits.sections_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 150},
      {"id": uuid.uuid4(), "key": "limits.sections_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 500},
      {"id": uuid.uuid4(), "key": "limits.tutor_sections_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 10},
      {"id": uuid.uuid4(), "key": "limits.tutor_sections_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 70},
      {"id": uuid.uuid4(), "key": "limits.tutor_sections_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 150},
      {"id": uuid.uuid4(), "key": "limits.tutor_sections_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 500},
      {"id": uuid.uuid4(), "key": "limits.fenster_widgets_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "limits.fenster_widgets_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "limits.fenster_widgets_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 40},
      {"id": uuid.uuid4(), "key": "limits.fenster_widgets_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 120},
      {"id": uuid.uuid4(), "key": "limits.ocr_files_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "limits.ocr_files_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 10},
      {"id": uuid.uuid4(), "key": "limits.ocr_files_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 30},
      {"id": uuid.uuid4(), "key": "limits.ocr_files_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 90},
      {"id": uuid.uuid4(), "key": "limits.history_lessons_kept", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 3},
      {"id": uuid.uuid4(), "key": "limits.history_lessons_kept", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 20},
      {"id": uuid.uuid4(), "key": "limits.history_lessons_kept", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 50},
      {"id": uuid.uuid4(), "key": "limits.history_lessons_kept", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 80},
      {"id": uuid.uuid4(), "key": "limits.max_file_upload_bytes", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "limits.max_file_upload_bytes", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 1048576},
      {"id": uuid.uuid4(), "key": "limits.max_file_upload_bytes", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 2097152},
      {"id": uuid.uuid4(), "key": "limits.max_file_upload_bytes", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 5242880},
      {"id": uuid.uuid4(), "key": "limits.youtube_capture_minutes_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "limits.youtube_capture_minutes_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 60},
      {"id": uuid.uuid4(), "key": "limits.youtube_capture_minutes_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 200},
      {"id": uuid.uuid4(), "key": "limits.youtube_capture_minutes_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 700},
      {"id": uuid.uuid4(), "key": "limits.image_generations_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "limits.image_generations_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 15},
      {"id": uuid.uuid4(), "key": "limits.image_generations_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 45},
      {"id": uuid.uuid4(), "key": "limits.image_generations_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 150},
      {"id": uuid.uuid4(), "key": "tutor.passive_lessons_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "tutor.passive_lessons_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 70},
      {"id": uuid.uuid4(), "key": "tutor.passive_lessons_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 150},
      {"id": uuid.uuid4(), "key": "tutor.passive_lessons_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 500},
      {"id": uuid.uuid4(), "key": "tutor.active_tokens_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "tutor.active_tokens_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "tutor.active_tokens_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "tutor.active_tokens_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 40000},
      {"id": uuid.uuid4(), "key": "career.mock_exams_count", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "career.mock_exams_count", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 1},
      {"id": uuid.uuid4(), "key": "career.mock_exams_count", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 4},
      {"id": uuid.uuid4(), "key": "career.mock_exams_count", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 15},
      {"id": uuid.uuid4(), "key": "career.mock_exams_token_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "career.mock_exams_token_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 10000},
      {"id": uuid.uuid4(), "key": "career.mock_exams_token_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 20000},
      {"id": uuid.uuid4(), "key": "career.mock_exams_token_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 50000},
      {"id": uuid.uuid4(), "key": "career.mock_interviews_count", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "career.mock_interviews_count", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "career.mock_interviews_count", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 1},
      {"id": uuid.uuid4(), "key": "career.mock_interviews_count", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 10},
      {"id": uuid.uuid4(), "key": "career.mock_interviews_minutes_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "career.mock_interviews_minutes_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 0},
      {"id": uuid.uuid4(), "key": "career.mock_interviews_minutes_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 15},
      {"id": uuid.uuid4(), "key": "career.mock_interviews_minutes_cap", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 30},
      {"id": uuid.uuid4(), "key": "fenster.widgets_tier", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": "none"},
      {"id": uuid.uuid4(), "key": "fenster.widgets_tier", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": "none"},
      {"id": uuid.uuid4(), "key": "fenster.widgets_tier", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": "flash"},
      {"id": uuid.uuid4(), "key": "fenster.widgets_tier", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": "reasoning"},
      {"id": uuid.uuid4(), "key": "themes.allowed", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": ["essential_focus"]},
      {"id": uuid.uuid4(), "key": "themes.allowed", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": ["essential_focus", "cliffside_serenity"]},
      {"id": uuid.uuid4(), "key": "themes.allowed", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": ["essential_focus", "oceanic_logic", "deep_forest", "stochastic_library", "cliffside_serenity"]},
      {"id": uuid.uuid4(), "key": "themes.allowed", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": ["essential_focus", "oceanic_logic", "deep_forest", "stochastic_library", "cliffside_serenity"]},
    ]
    for entry in runtime_entries:
      # Skip incomplete entries when tier IDs are missing.
      if entry["subscription_tier_id"] is None:
        continue
      entry_payload = dict(entry)
      upsert_runtime_sql = (
        "INSERT INTO runtime_config_values (id, key, scope, subscription_tier_id, value_json) "
        "VALUES (:id, :key, :scope, :subscription_tier_id, :value_json) "
        "ON CONFLICT (key, subscription_tier_id) WHERE scope = 'TIER' "
        "DO UPDATE SET value_json = EXCLUDED.value_json"
      )
      stmt = text(upsert_runtime_sql)
      stmt = stmt.bindparams(bindparam("value_json", type_=JSONB))
      await connection.execute(stmt, entry_payload)
