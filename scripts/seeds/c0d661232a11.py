"""Seed canonical roles, permissions, and feature flag descriptions."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_ROLE_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
  ("Super Admin", "GLOBAL", "Global super administrator."),
  ("Admin", "GLOBAL", "Internal administrator."),
  ("User", "GLOBAL", "Internal user."),
  ("Tenant_Admin", "TENANT", "Tenant administrator."),
  ("Tenant_User", "TENANT", "Tenant user."),
)

_PERMISSION_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
  ("user_data:view", "View User Data", "View user account data and onboarding details."),
  ("user_data:edit", "Edit User Data", "Edit user status, role, and tier data."),
  ("user_data:discard", "Discard User Data", "Soft-delete users by marking them discarded."),
  ("user_data:restore", "Restore User Data", "Restore previously discarded users."),
  ("user_data:delete_permanent", "Delete User Data Permanently", "Permanently delete users and cascaded data."),
  ("rbac:role_create", "Create Roles", "Create RBAC roles."),
  ("rbac:role_permissions_update", "Update Role Permissions", "Assign permissions to roles."),
  ("flags:read", "Read Feature Flags", "Read feature flag definitions and effective values."),
  ("flags:write_global", "Write Global Feature Flags", "Create and update global feature flag defaults."),
  ("flags:write_tier", "Write Tier Feature Flags", "Set feature flag overrides at tier scope."),
  ("flags:write_org", "Write Tenant Feature Flags", "Set feature flag overrides at tenant scope."),
  ("config:read", "Read Runtime Config", "Read runtime config definitions and values."),
  ("config:write_global", "Write Global Runtime Config", "Update global runtime config."),
  ("config:write_tier", "Write Tier Runtime Config", "Update tier runtime config."),
  ("config:write_org", "Write Tenant Runtime Config", "Update tenant runtime config."),
  ("user:self_read", "Read Own Profile", "Read own user profile."),
  ("user:quota_read", "Read Own Quota", "Read own quota summary."),
  ("user:features_read", "Read Own Features", "Read own effective features and permissions."),
  ("lesson:list_own", "List Own Lessons", "List own lessons."),
  ("lesson:view_own", "View Own Lesson", "View own lesson details."),
  ("lesson:outline_own", "View Own Lesson Outline", "View own lesson outline."),
  ("lesson:generate", "Generate Lessons", "Start lesson generation."),
  ("lesson:outcomes", "Generate Lesson Outcomes", "Run outcomes generation preflight."),
  ("lesson:job_create", "Create Lesson Job", "Create background lesson jobs."),
  ("section:view_own", "View Own Sections", "Read own lesson sections."),
  ("job:create_own", "Create Own Jobs", "Create own background jobs."),
  ("job:view_own", "View Own Jobs", "Read own job status and results."),
  ("job:retry_own", "Retry Own Jobs", "Retry own jobs."),
  ("job:cancel_own", "Cancel Own Jobs", "Cancel own jobs."),
  ("media:view_own", "View Own Media", "Access own generated media."),
  ("notification:list_own", "List Own Notifications", "List own in-app notifications."),
  ("push:subscribe_own", "Subscribe Push", "Create own push subscription."),
  ("push:unsubscribe_own", "Unsubscribe Push", "Delete own push subscription."),
  ("tutor:audio_view_own", "View Own Tutor Audio", "Access own tutor audio results."),
  ("research:use", "Use Research", "Run research discovery and synthesis."),
  ("writing:check", "Run Writing Check", "Run writing feedback checks."),
  ("ocr:extract", "Extract OCR Text", "Extract text from uploaded images."),
  ("fenster:view", "View Fenster Widget", "Read and render fenster widgets."),
  ("admin:jobs_read", "Read Admin Jobs", "Read administrative job listings."),
  ("admin:lessons_read", "Read Admin Lessons", "Read administrative lesson listings."),
  ("admin:llm_calls_read", "Read Admin LLM Calls", "Read administrative LLM audit listings."),
  ("admin:artifacts_read", "Read Admin Artifacts", "Read generated artifacts and media listings."),
  ("admin:maintenance_archive_lessons", "Run Archive Maintenance", "Run lesson archive maintenance jobs."),
  ("lesson_data:discard", "Discard Lesson Data", "Soft-delete lesson content by archiving."),
  ("lesson_data:restore", "Restore Lesson Data", "Restore archived lesson content."),
  ("lesson_data:delete_permanent", "Delete Lesson Data Permanently", "Permanently delete lesson content."),
  ("data_transfer:export_create", "Create Data Export", "Start data export runs."),
  ("data_transfer:export_read", "Read Data Export", "Read data export runs."),
  ("data_transfer:download_link_create", "Create Export Download Links", "Generate export download links."),
  ("data_transfer:hydrate_create", "Create Data Hydrate", "Start data hydrate runs."),
  ("data_transfer:hydrate_read", "Read Data Hydrate", "Read data hydrate runs."),
)

_FEATURE_FLAG_DESCRIPTIONS: tuple[tuple[str, str], ...] = (
  ("feature.tutor.mode", "Enable tutor mode."),
  ("feature.tutor.active", "Enable active tutor sessions."),
  ("feature.mock_exams", "Enable mock exams."),
  ("feature.mock_interviews", "Enable mock interviews."),
  ("feature.fenster", "Enable fenster widgets."),
  ("feature.youtube_capture", "Enable YouTube capture."),
  ("feature.image_generation", "Enable image generation."),
  ("feature.ocr", "Enable OCR extraction."),
  ("feature.writing", "Enable writing check."),
  ("feature.research", "Enable research workflows."),
  ("feature.notifications.email", "Enable notification emails."),
)

_ROLE_PERMISSION_DEFAULTS: dict[str, set[str]] = {
  "Admin": {
    "user_data:view",
    "user_data:edit",
    "user_data:discard",
    "user_data:restore",
    "rbac:role_create",
    "rbac:role_permissions_update",
    "flags:read",
    "flags:write_global",
    "flags:write_tier",
    "flags:write_org",
    "config:read",
    "config:write_global",
    "config:write_tier",
    "config:write_org",
    "lesson:list_own",
    "lesson:view_own",
    "lesson:outline_own",
    "lesson:generate",
    "lesson:outcomes",
    "lesson:job_create",
    "section:view_own",
    "job:create_own",
    "job:view_own",
    "job:retry_own",
    "job:cancel_own",
    "media:view_own",
    "notification:list_own",
    "push:subscribe_own",
    "push:unsubscribe_own",
    "tutor:audio_view_own",
    "research:use",
    "writing:check",
    "ocr:extract",
    "fenster:view",
    "user:self_read",
    "user:quota_read",
    "user:features_read",
    "admin:jobs_read",
    "admin:lessons_read",
    "admin:llm_calls_read",
    "admin:artifacts_read",
    "admin:maintenance_archive_lessons",
    "data_transfer:export_create",
    "data_transfer:export_read",
    "data_transfer:download_link_create",
    "data_transfer:hydrate_create",
    "data_transfer:hydrate_read",
  },
  "User": {
    "lesson:list_own",
    "lesson:view_own",
    "lesson:outline_own",
    "lesson:generate",
    "lesson:outcomes",
    "lesson:job_create",
    "section:view_own",
    "job:create_own",
    "job:view_own",
    "job:retry_own",
    "job:cancel_own",
    "media:view_own",
    "notification:list_own",
    "push:subscribe_own",
    "push:unsubscribe_own",
    "tutor:audio_view_own",
    "research:use",
    "writing:check",
    "ocr:extract",
    "fenster:view",
    "user:self_read",
    "user:quota_read",
    "user:features_read",
    "data_transfer:export_read",
    "data_transfer:hydrate_read",
  },
  "Tenant_Admin": {
    "user_data:view",
    "user_data:edit",
    "user_data:discard",
    "user_data:restore",
    "flags:read",
    "flags:write_org",
    "config:read",
    "config:write_org",
    "lesson:list_own",
    "lesson:view_own",
    "lesson:outline_own",
    "lesson:generate",
    "lesson:outcomes",
    "lesson:job_create",
    "section:view_own",
    "job:create_own",
    "job:view_own",
    "job:retry_own",
    "job:cancel_own",
    "media:view_own",
    "notification:list_own",
    "push:subscribe_own",
    "push:unsubscribe_own",
    "tutor:audio_view_own",
    "research:use",
    "writing:check",
    "ocr:extract",
    "fenster:view",
    "user:self_read",
    "user:quota_read",
    "user:features_read",
  },
  "Tenant_User": {
    "lesson:list_own",
    "lesson:view_own",
    "lesson:outline_own",
    "lesson:generate",
    "lesson:outcomes",
    "lesson:job_create",
    "section:view_own",
    "job:create_own",
    "job:view_own",
    "job:retry_own",
    "job:cancel_own",
    "media:view_own",
    "notification:list_own",
    "push:subscribe_own",
    "push:unsubscribe_own",
    "tutor:audio_view_own",
    "research:use",
    "writing:check",
    "ocr:extract",
    "fenster:view",
    "user:self_read",
    "user:quota_read",
    "user:features_read",
  },
}


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


def _feature_flag_to_permission_slug(key: str) -> str:
  """Map a feature flag key to the canonical permission slug."""
  suffix = key[8:] if key.startswith("feature.") else key
  suffix = suffix.replace(".", "_").replace("-", "_").replace(":", "_").strip("_")
  return f"feature_{suffix}:use"


async def seed(connection: AsyncConnection) -> None:
  """Upsert canonical RBAC defaults and feature metadata."""
  roles_ready = await _ensure_columns(connection, table_name="roles", columns=["id", "name", "level", "description"])
  permissions_ready = await _ensure_columns(connection, table_name="permissions", columns=["id", "slug", "display_name", "description"])
  role_permissions_ready = await _ensure_columns(connection, table_name="role_permissions", columns=["role_id", "permission_id"])
  feature_flags_ready = await _ensure_columns(connection, table_name="feature_flags", columns=["id", "key", "description", "default_enabled"])
  if not roles_ready or not permissions_ready or not role_permissions_ready:
    return

  upsert_role_statement = text(
    """
    INSERT INTO roles (id, name, level, description)
    VALUES (:id, :name, :level, :description)
    ON CONFLICT (name) DO UPDATE
    SET level = EXCLUDED.level,
        description = EXCLUDED.description
    """
  )
  for name, level, description in _ROLE_DEFINITIONS:
    await connection.execute(upsert_role_statement, {"id": uuid.uuid4(), "name": name, "level": level, "description": description})
  # Rename legacy tenant role names to canonical names when present.
  await connection.execute(text("UPDATE roles SET name = 'Tenant_Admin' WHERE name = 'Org Admin'"))
  await connection.execute(text("UPDATE roles SET name = 'Tenant_User' WHERE name = 'Org Member'"))

  if feature_flags_ready:
    upsert_flag_statement = text(
      """
      INSERT INTO feature_flags (id, key, description, default_enabled)
      VALUES (:id, :key, :description, :default_enabled)
      ON CONFLICT (key) DO UPDATE
      SET description = EXCLUDED.description
      """
    )
    for key, description in _FEATURE_FLAG_DESCRIPTIONS:
      await connection.execute(upsert_flag_statement, {"id": uuid.uuid4(), "key": key, "description": description, "default_enabled": False})

  permission_defs = list(_PERMISSION_DEFINITIONS)
  if feature_flags_ready:
    flags_result = await connection.execute(text("SELECT key FROM feature_flags"))
    for row in flags_result.fetchall():
      key = str(row[0])
      slug = _feature_flag_to_permission_slug(key)
      permission_defs.append((slug, f"Use {key}", f"Access endpoints gated by feature flag `{key}`."))

  upsert_permission_statement = text(
    """
    INSERT INTO permissions (id, slug, display_name, description)
    VALUES (:id, :slug, :display_name, :description)
    ON CONFLICT (slug) DO UPDATE
    SET display_name = EXCLUDED.display_name,
        description = EXCLUDED.description
    """
  )
  for slug, display_name, description in permission_defs:
    await connection.execute(upsert_permission_statement, {"id": uuid.uuid4(), "slug": slug, "display_name": display_name, "description": description})

  roles_result = await connection.execute(text("SELECT id, name FROM roles WHERE name = ANY(:names)"), {"names": [name for name, _level, _desc in _ROLE_DEFINITIONS]})
  role_ids = {str(row[1]): row[0] for row in roles_result.fetchall()}
  permissions_result = await connection.execute(text("SELECT id, slug FROM permissions"))
  permission_ids = {str(row[1]): row[0] for row in permissions_result.fetchall()}
  feature_permission_slugs = {slug for slug in permission_ids.keys() if slug.startswith("feature_") and slug.endswith(":use")}

  # Backfill strict permission-feature flags so every permission can be feature-gated.
  if feature_flags_ready:
    for slug in sorted(permission_ids.keys()):
      perm_key = f"perm.{slug}"
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
        {"id": uuid.uuid4(), "key": perm_key, "description": f"Enable permission `{slug}`.", "default_enabled": True},
      )

    # Keep strict chain deterministic by ensuring tier rows exist for all flags.
    if await _ensure_columns(connection, table_name="subscription_tiers", columns=["id", "name"]) and await _ensure_columns(connection, table_name="subscription_tier_feature_flags", columns=["subscription_tier_id", "feature_flag_id", "enabled"]):
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

    # Keep strict tenant chain deterministic by ensuring org rows exist.
    if await _ensure_columns(connection, table_name="organizations", columns=["id"]) and await _ensure_columns(connection, table_name="organization_feature_flags", columns=["org_id", "feature_flag_id", "enabled"]):
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

  insert_role_permission_statement = text(
    """
    INSERT INTO role_permissions (role_id, permission_id)
    VALUES (:role_id, :permission_id)
    ON CONFLICT (role_id, permission_id) DO NOTHING
    """
  )

  for role_name, permission_slugs in _ROLE_PERMISSION_DEFAULTS.items():
    role_id = role_ids.get(role_name)
    if role_id is None:
      continue
    # Preserve existing custom role grants and only add missing defaults.
    effective_slugs = set(permission_slugs)
    effective_slugs.update(feature_permission_slugs)
    for slug in sorted(effective_slugs):
      permission_id = permission_ids.get(slug)
      if permission_id is None:
        continue
      await connection.execute(insert_role_permission_statement, {"role_id": role_id, "permission_id": permission_id})

  super_admin_role_id = role_ids.get("Super Admin")
  if super_admin_role_id is not None:
    # Grant all permissions without removing any existing explicit grants.
    await connection.execute(
      text(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT :role_id, permissions.id
        FROM permissions
        ON CONFLICT (role_id, permission_id) DO NOTHING
        """
      ),
      {"role_id": super_admin_role_id},
    )

  # Classify seeded tiers so strict tenant-chain routing can branch deterministically.
  if await _column_exists(connection, table_name="subscription_tiers", column_name="is_tenant_tier"):
    # Keep all tiers non-tenant until tenant-specific tiers are explicitly introduced.
    await connection.execute(text("UPDATE subscription_tiers SET is_tenant_tier = FALSE"))
