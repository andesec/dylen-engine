"""Consolidated seed data for the baseline migration revision."""

from __future__ import annotations

import uuid

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection

# Fixed UUIDs for consistent environments
ROLE_SUPER_ADMIN_ID = uuid.UUID("3e56ebfc-1d62-42cb-a920-ab6e916e58bf")
ROLE_ADMIN_ID = uuid.UUID("33caeb8d-9824-4506-953a-c5e949db3dba")
ROLE_USER_ID = uuid.UUID("34caeb8d-9824-4506-953a-c5e949db3dba")
ROLE_ORG_ADMIN_ID = uuid.UUID("102d6fab-322c-48f8-a8f8-0d9e5eb52aa6")
ROLE_ORG_MEMBER_ID = uuid.UUID("d028adea-31a6-48fb-afd8-777a4cd410b4")

# Permission UUIDs - fixed for consistency
PERMISSIONS = {
  "user:manage": uuid.UUID("2fcaeb8d-9824-4506-953a-c5e949db3db8"),
  "user:quota_read": uuid.UUID("3fcaeb8d-9824-4506-953a-c5e949db3db8"),
  "user:self_read": uuid.UUID("4fcaeb8d-9824-4506-953a-c5e949db3db8"),
  "user:features_read": uuid.UUID("5fcaeb8d-9824-4506-953a-c5e949db3db8"),
  "user_data:view": uuid.UUID("6fcaeb8d-9824-4506-953a-c5e949db3db8"),
  "user_data:edit": uuid.UUID("7fcaeb8d-9824-4506-953a-c5e949db3db8"),
  "user_data:discard": uuid.UUID("8fcaeb8d-9824-4506-953a-c5e949db3db8"),
  "user_data:restore": uuid.UUID("9fcaeb8d-9824-4506-953a-c5e949db3db8"),
  "user_data:delete_permanent": uuid.UUID("afcaeb8d-9824-4506-953a-c5e949db3db8"),
  "rbac:role_create": uuid.UUID("bfcaeb8d-9824-4506-953a-c5e949db3db8"),
  "rbac:role_permissions_update": uuid.UUID("cfcaeb8d-9824-4506-953a-c5e949db3db8"),
  "config:read": uuid.UUID("dfcaeb8d-9824-4506-953a-c5e949db3db8"),
  "config:write_global": uuid.UUID("efcaeb8d-9824-4506-953a-c5e949db3db8"),
  "config:write_tier": uuid.UUID("ffcaeb8d-9824-4506-953a-c5e949db3db8"),
  "config:write_org": uuid.UUID("01caeb8d-9824-4506-953a-c5e949db3db9"),
  "flags:read": uuid.UUID("11caeb8d-9824-4506-953a-c5e949db3db9"),
  "flags:write_global": uuid.UUID("12caeb8d-9824-4506-953a-c5e949db3db9"),
  "flags:write_tier": uuid.UUID("13caeb8d-9824-4506-953a-c5e949db3db9"),
  "flags:write_org": uuid.UUID("14caeb8d-9824-4506-953a-c5e949db3db9"),
  "lesson:list_own": uuid.UUID("15caeb8d-9824-4506-953a-c5e949db3db9"),
  "lesson:outcomes": uuid.UUID("16caeb8d-9824-4506-953a-c5e949db3db9"),
  "lesson:generate": uuid.UUID("17caeb8d-9824-4506-953a-c5e949db3db9"),
  "lesson:view_own": uuid.UUID("18caeb8d-9824-4506-953a-c5e949db3db9"),
  "lesson:outline_own": uuid.UUID("19caeb8d-9824-4506-953a-c5e949db3db9"),
  "lesson:job_create": uuid.UUID("1acabeb8-9824-4506-953a-c5e949db3db9"),
  "section:view_own": uuid.UUID("1bcaeb8d-9824-4506-953a-c5e949db3db9"),
  "job:create_own": uuid.UUID("1ccaeb8d-9824-4506-953a-c5e949db3db9"),
  "job:retry_own": uuid.UUID("1dcaeb8d-9824-4506-953a-c5e949db3db9"),
  "job:cancel_own": uuid.UUID("1ecaeb8d-9824-4506-953a-c5e949db3db9"),
  "job:view_own": uuid.UUID("1fcaeb8d-9824-4506-953a-c5e949db3db9"),
  "media:view_own": uuid.UUID("20caeb8d-9824-4506-953a-c5e949db3db9"),
  "notification:list_own": uuid.UUID("21caeb8d-9824-4506-953a-c5e949db3db9"),
  "push:subscribe_own": uuid.UUID("22caeb8d-9824-4506-953a-c5e949db3db9"),
  "push:unsubscribe_own": uuid.UUID("23caeb8d-9824-4506-953a-c5e949db3db9"),
  "tutor:audio_view_own": uuid.UUID("24caeb8d-9824-4506-953a-c5e949db3db9"),
  "fenster:view": uuid.UUID("25caeb8d-9824-4506-953a-c5e949db3db9"),
  "research:use": uuid.UUID("26caeb8d-9824-4506-953a-c5e949db3db9"),
  "writing:check": uuid.UUID("27caeb8d-9824-4506-953a-c5e949db3db9"),
  "ocr:extract": uuid.UUID("28caeb8d-9824-4506-953a-c5e949db3db9"),
  "admin:maintenance_archive_lessons": uuid.UUID("29caeb8d-9824-4506-953a-c5e949db3db9"),
  "admin:jobs_read": uuid.UUID("2acabeb8-9824-4506-953a-c5e949db3db9"),
  "admin:lessons_read": uuid.UUID("2bcaeb8d-9824-4506-953a-c5e949db3db9"),
  "admin:llm_calls_read": uuid.UUID("2ccaeb8d-9824-4506-953a-c5e949db3db9"),
  "admin:artifacts_read": uuid.UUID("2dcaeb8d-9824-4506-953a-c5e949db3db9"),
  "data_transfer:export_create": uuid.UUID("2ecaeb8d-9824-4506-953a-c5e949db3db9"),
  "data_transfer:export_read": uuid.UUID("2fcaeb8d-9824-4506-953a-c5e949db3dba"),
  "data_transfer:download_link_create": uuid.UUID("30caeb8d-9824-4506-953a-c5e949db3dba"),
  "data_transfer:hydrate_create": uuid.UUID("31caeb8d-9824-4506-953a-c5e949db3dba"),
  "data_transfer:hydrate_read": uuid.UUID("32caeb8d-9824-4506-953a-c5e949db3dba"),
}

# Superadmin configuration
SUPERADMIN_EMAIL = "dylen.app@gmail.com"
SUPERADMIN_PLACEHOLDER_UID = "bootstrap-dylen-superadmin"
SUPERADMIN_NAME = "Dylen Superadmin"


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


async def _seed_rbac_core(connection: AsyncConnection) -> None:
  """Seed core RBAC roles and permissions."""
  # Seed roles
  if await _ensure_columns(connection, table_name="roles", columns=["id", "name", "level", "description"]):
    await connection.execute(
      text(
        """
        INSERT INTO roles (id, name, level, description)
        VALUES
          (:id1, :name1, :level1, :desc1),
          (:id2, :name2, :level2, :desc2),
          (:id3, :name3, :level3, :desc3),
          (:id4, :name4, :level4, :desc4),
          (:id5, :name5, :level5, :desc5)
        ON CONFLICT (name) DO UPDATE
        SET level = EXCLUDED.level,
            description = EXCLUDED.description
        """
      ),
      {
        "id1": ROLE_SUPER_ADMIN_ID,
        "name1": "Super Admin",
        "level1": "GLOBAL",
        "desc1": "Global super administrator.",
        "id2": ROLE_ADMIN_ID,
        "name2": "Admin",
        "level2": "GLOBAL",
        "desc2": "Internal administrator.",
        "id3": ROLE_USER_ID,
        "name3": "User",
        "level3": "GLOBAL",
        "desc3": "Internal user.",
        "id4": ROLE_ORG_ADMIN_ID,
        "name4": "Tenant_Admin",
        "level4": "TENANT",
        "desc4": "Tenant administrator.",
        "id5": ROLE_ORG_MEMBER_ID,
        "name5": "Tenant_User",
        "level5": "TENANT",
        "desc5": "Tenant user.",
      },
    )

  # Seed permissions
  if await _ensure_columns(connection, table_name="permissions", columns=["id", "slug", "display_name", "description"]):
    permission_defs = [
      {"slug": "user:manage", "display_name": "Manage Users", "description": "List users and update roles/statuses."},
      {"slug": "user:quota_read", "display_name": "Read User Quota", "description": "View quota information for users."},
      {"slug": "user:self_read", "display_name": "Read Own User", "description": "View own user information."},
      {"slug": "user:features_read", "display_name": "Read User Features", "description": "View feature flags for users."},
      {"slug": "user_data:view", "display_name": "View User Data", "description": "View user data in admin panel."},
      {"slug": "user_data:edit", "display_name": "Edit User Data", "description": "Edit user data in admin panel."},
      {"slug": "user_data:discard", "display_name": "Discard User", "description": "Archive/discard user accounts."},
      {"slug": "user_data:restore", "display_name": "Restore User", "description": "Restore archived user accounts."},
      {"slug": "user_data:delete_permanent", "display_name": "Delete User Permanently", "description": "Permanently delete user accounts."},
      {"slug": "rbac:role_create", "display_name": "Create Role", "description": "Create new RBAC roles."},
      {"slug": "rbac:role_permissions_update", "display_name": "Update Role Permissions", "description": "Update permissions assigned to roles."},
      {"slug": "config:read", "display_name": "Read Configuration", "description": "Read runtime configuration."},
      {"slug": "config:write_global", "display_name": "Write Global Config", "description": "Write global runtime configuration."},
      {"slug": "config:write_tier", "display_name": "Write Tier Config", "description": "Write tier-scoped configuration."},
      {"slug": "config:write_org", "display_name": "Write Org Config", "description": "Write organization-scoped configuration."},
      {"slug": "flags:read", "display_name": "Read Feature Flags", "description": "Read feature flag definitions."},
      {"slug": "flags:write_global", "display_name": "Write Global Flags", "description": "Write global feature flag settings."},
      {"slug": "flags:write_tier", "display_name": "Write Tier Flags", "description": "Write tier-scoped feature flags."},
      {"slug": "flags:write_org", "display_name": "Write Org Flags", "description": "Write organization-scoped feature flags."},
      {"slug": "lesson:list_own", "display_name": "List Own Lessons", "description": "List own lessons."},
      {"slug": "lesson:outcomes", "display_name": "Generate Lesson Outcomes", "description": "Generate learning outcomes for lessons."},
      {"slug": "lesson:generate", "display_name": "Generate Lesson", "description": "Generate new lessons."},
      {"slug": "lesson:view_own", "display_name": "View Own Lesson", "description": "View own lesson details."},
      {"slug": "lesson:outline_own", "display_name": "View Own Lesson Outline", "description": "View own lesson outline."},
      {"slug": "lesson:job_create", "display_name": "Create Lesson Job", "description": "Create jobs for lesson generation."},
      {"slug": "section:view_own", "display_name": "View Own Section", "description": "View own lesson sections."},
      {"slug": "job:create_own", "display_name": "Create Own Job", "description": "Create own jobs."},
      {"slug": "job:retry_own", "display_name": "Retry Own Job", "description": "Retry own jobs."},
      {"slug": "job:cancel_own", "display_name": "Cancel Own Job", "description": "Cancel own jobs."},
      {"slug": "job:view_own", "display_name": "View Own Job", "description": "View own job status."},
      {"slug": "media:view_own", "display_name": "View Own Media", "description": "View own media files."},
      {"slug": "notification:list_own", "display_name": "List Own Notifications", "description": "List own notifications."},
      {"slug": "push:subscribe_own", "display_name": "Subscribe to Push", "description": "Subscribe to push notifications."},
      {"slug": "push:unsubscribe_own", "display_name": "Unsubscribe from Push", "description": "Unsubscribe from push notifications."},
      {"slug": "tutor:audio_view_own", "display_name": "View Own Tutor Audio", "description": "View own tutor audio content."},
      {"slug": "fenster:view", "display_name": "View Fenster", "description": "View Fenster widgets."},
      {"slug": "research:use", "display_name": "Use Research", "description": "Use research features."},
      {"slug": "writing:check", "display_name": "Check Writing", "description": "Use writing check features."},
      {"slug": "ocr:extract", "display_name": "Extract OCR", "description": "Use OCR text extraction."},
      {"slug": "admin:maintenance_archive_lessons", "display_name": "Archive Lessons Maintenance", "description": "Run lesson archival maintenance tasks."},
      {"slug": "admin:jobs_read", "display_name": "Read Jobs", "description": "View all jobs in admin panel."},
      {"slug": "admin:lessons_read", "display_name": "Read Lessons", "description": "View all lessons in admin panel."},
      {"slug": "admin:llm_calls_read", "display_name": "Read LLM Calls", "description": "View LLM API call logs."},
      {"slug": "admin:artifacts_read", "display_name": "Read Artifacts", "description": "View all artifacts in admin panel."},
      {"slug": "data_transfer:export_create", "display_name": "Create Data Export", "description": "Create data export jobs."},
      {"slug": "data_transfer:export_read", "display_name": "Read Data Export", "description": "View data export status."},
      {"slug": "data_transfer:download_link_create", "display_name": "Create Download Link", "description": "Create download links for exports."},
      {"slug": "data_transfer:hydrate_create", "display_name": "Create Data Hydrate", "description": "Create data hydration jobs."},
      {"slug": "data_transfer:hydrate_read", "display_name": "Read Data Hydrate", "description": "View data hydration status."},
    ]

    for perm_def in permission_defs:
      perm_id = PERMISSIONS.get(perm_def["slug"])
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

  # Seed role-permission mappings
  if await _ensure_columns(connection, table_name="role_permissions", columns=["role_id", "permission_id"]):
    # Define permission sets for each role (from c0d661232a11.py)
    role_permission_grants = {
      "Admin": [
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
      ],
      "User": [
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
      ],
      "Tenant_Admin": [
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
      ],
      "Tenant_User": [
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
      ],
    }

    # Map role names to role IDs
    role_id_map = {"Super Admin": ROLE_SUPER_ADMIN_ID, "Admin": ROLE_ADMIN_ID, "User": ROLE_USER_ID, "Tenant_Admin": ROLE_ORG_ADMIN_ID, "Tenant_User": ROLE_ORG_MEMBER_ID}

    # Super Admin gets ALL permissions
    for permission_id in PERMISSIONS.values():
      await connection.execute(
        text(
          """
          INSERT INTO role_permissions (role_id, permission_id)
          VALUES (:role_id, :permission_id)
          ON CONFLICT (role_id, permission_id) DO NOTHING
          """
        ),
        {"role_id": ROLE_SUPER_ADMIN_ID, "permission_id": permission_id},
      )

    # Grant specific permissions to other roles
    for role_name, perm_slugs in role_permission_grants.items():
      role_id = role_id_map.get(role_name)
      if role_id is None:
        continue
      for perm_slug in perm_slugs:
        perm_id = PERMISSIONS.get(perm_slug)
        if perm_id is None:
          continue
        await connection.execute(
          text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            VALUES (:role_id, :permission_id)
            ON CONFLICT (role_id, permission_id) DO NOTHING
            """
          ),
          {"role_id": role_id, "permission_id": perm_id},
        )


async def _seed_subscription_tiers(connection: AsyncConnection) -> dict[str, int]:
  """Seed subscription tiers and return tier_name -> tier_id mapping."""
  tier_ids = {}

  # Check if we need to update subscription_tiers schema for new columns
  has_concurrent_limits = await _column_exists(connection, table_name="subscription_tiers", column_name="concurrent_lesson_limit")
  has_tenant_tier = await _column_exists(connection, table_name="subscription_tiers", column_name="is_tenant_tier")

  if has_concurrent_limits and has_tenant_tier:
    # New schema with concurrent limits and tenant tier flag
    if await _ensure_columns(
      connection,
      table_name="subscription_tiers",
      columns=[
        "name",
        "max_file_upload_kb",
        "highest_lesson_depth",
        "max_sections_per_lesson",
        "file_upload_quota",
        "image_upload_quota",
        "gen_sections_quota",
        "research_quota",
        "concurrent_lesson_limit",
        "concurrent_research_limit",
        "concurrent_writing_limit",
        "concurrent_tutor_limit",
        "is_tenant_tier",
        "tutor_mode_enabled",
        "tutor_voice_tier",
      ],
    ):
      await connection.execute(
        text(
          """
          INSERT INTO subscription_tiers (
            name, max_file_upload_kb, highest_lesson_depth, max_sections_per_lesson,
            file_upload_quota, image_upload_quota, gen_sections_quota, research_quota,
            concurrent_lesson_limit, concurrent_research_limit, concurrent_writing_limit, concurrent_tutor_limit,
            is_tenant_tier, tutor_mode_enabled, tutor_voice_tier
          )
          VALUES
            (:name1, :mfu1, :depth1, :sections1, :fuq1, :iuq1, :gsq1, :rq1, :cll1, :crl1, :cwl1, :ctl1, :itt1, :tutor1, :voice1),
            (:name2, :mfu2, :depth2, :sections2, :fuq2, :iuq2, :gsq2, :rq2, :cll2, :crl2, :cwl2, :ctl2, :itt2, :tutor2, :voice2),
            (:name3, :mfu3, :depth3, :sections3, :fuq3, :iuq3, :gsq3, :rq3, :cll3, :crl3, :cwl3, :ctl3, :itt3, :tutor3, :voice3),
            (:name4, :mfu4, :depth4, :sections4, :fuq4, :iuq4, :gsq4, :rq4, :cll4, :crl4, :cwl4, :ctl4, :itt4, :tutor4, :voice4)
          ON CONFLICT (name) DO UPDATE
          SET max_file_upload_kb = EXCLUDED.max_file_upload_kb,
              highest_lesson_depth = EXCLUDED.highest_lesson_depth,
              max_sections_per_lesson = EXCLUDED.max_sections_per_lesson,
              file_upload_quota = EXCLUDED.file_upload_quota,
              image_upload_quota = EXCLUDED.image_upload_quota,    
              gen_sections_quota = EXCLUDED.gen_sections_quota,
              research_quota = EXCLUDED.research_quota,
              concurrent_lesson_limit = EXCLUDED.concurrent_lesson_limit,
              concurrent_research_limit = EXCLUDED.concurrent_research_limit,
              concurrent_writing_limit = EXCLUDED.concurrent_writing_limit,
              concurrent_tutor_limit = EXCLUDED.concurrent_tutor_limit,
              is_tenant_tier = EXCLUDED.is_tenant_tier,
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
          "cll1": 1,
          "crl1": 1,
          "cwl1": 1,
          "ctl1": 1,
          "itt1": False,
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
          "cll2": 1,
          "crl2": 1,
          "cwl2": 1,
          "ctl2": 1,
          "itt2": False,
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
          "cll3": 1,
          "crl3": 1,
          "cwl3": 1,
          "ctl3": 1,
          "itt3": False,
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
          "cll4": 1,
          "crl4": 1,
          "cwl4": 1,
          "ctl4": 1,
          "itt4": False,
          "tutor4": True,
          "voice4": "premium",
        },
      )
  else:
    # Legacy schema without concurrent limits
    if await _ensure_columns(
      connection,
      table_name="subscription_tiers",
      columns=["name", "max_file_upload_kb", "highest_lesson_depth", "max_sections_per_lesson", "file_upload_quota", "image_upload_quota", "gen_sections_quota", "research_quota", "tutor_mode_enabled", "tutor_voice_tier"],
    ):
      await connection.execute(
        text(
          """
          INSERT INTO subscription_tiers (
            name, max_file_upload_kb, highest_lesson_depth, max_sections_per_lesson,
            file_upload_quota, image_upload_quota, gen_sections_quota, research_quota,
            tutor_mode_enabled, tutor_voice_tier
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

  # Load tier IDs for further processing
  tier_names = ["Free", "Starter", "Plus", "Pro"]
  tier_result = await connection.execute(text("SELECT id, name FROM subscription_tiers WHERE name = ANY(:names)"), {"names": tier_names})
  tier_rows = tier_result.fetchall()
  tier_ids = {row[1]: row[0] for row in tier_rows}

  return tier_ids


async def _seed_feature_flags(connection: AsyncConnection, tier_ids: dict[str, int]) -> None:
  """Seed feature flags and tier-specific assignments."""
  # Seed feature flags
  if await _ensure_columns(connection, table_name="feature_flags", columns=["id", "key", "description", "default_enabled"]):
    flag_defs = [
      # Product feature flags
      {"id": uuid.uuid4(), "key": "feature.tutor.mode", "description": "Enable tutor mode.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.tutor.active", "description": "Enable active tutor sessions.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.mock_exams", "description": "Enable mock exams.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.mock_interviews", "description": "Enable mock interviews.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.fenster", "description": "Enable Fenster widgets.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.youtube_capture", "description": "Enable YouTube capture.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.image_generation", "description": "Enable image generation.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.research", "description": "Enable research features.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.writing", "description": "Enable writing check features.", "default_enabled": False},
      {"id": uuid.uuid4(), "key": "feature.ocr", "description": "Enable OCR features.", "default_enabled": False},
    ]

    # Add permission feature flags for all permissions
    for perm_slug in PERMISSIONS.keys():
      flag_defs.append(
        {
          "id": uuid.uuid4(),
          "key": f"perm.{perm_slug}",
          "description": f"Permission gate for {perm_slug}",
          "default_enabled": True,  # Permission flags are enabled by default
        }
      )

    for flag in flag_defs:
      await connection.execute(
        text("INSERT INTO feature_flags (id, key, description, default_enabled) VALUES (:id, :key, :description, :default_enabled) ON CONFLICT (key) DO UPDATE SET description = EXCLUDED.description, default_enabled = EXCLUDED.default_enabled"), flag
      )

  # Seed tier-specific feature flag assignments
  if await _ensure_columns(connection, table_name="subscription_tier_feature_flags", columns=["subscription_tier_id", "feature_flag_id", "enabled"]) and tier_ids:
    # Product feature flags
    product_flag_keys = ["feature.tutor.mode", "feature.tutor.active", "feature.mock_exams", "feature.mock_interviews", "feature.fenster", "feature.youtube_capture", "feature.image_generation", "feature.research", "feature.writing", "feature.ocr"]
    product_flag_result = await connection.execute(text("SELECT id, key FROM feature_flags WHERE key = ANY(:keys)"), {"keys": product_flag_keys})
    product_flag_rows = product_flag_result.fetchall()
    product_flag_ids = {row[1]: row[0] for row in product_flag_rows}

    # Permission flags - get all perm.* flags
    perm_flag_keys = [f"perm.{perm_slug}" for perm_slug in PERMISSIONS.keys()]
    perm_flag_result = await connection.execute(text("SELECT id, key FROM feature_flags WHERE key = ANY(:keys)"), {"keys": perm_flag_keys})
    perm_flag_rows = perm_flag_result.fetchall()
    perm_flag_ids = {row[1]: row[0] for row in perm_flag_rows}

    flag_assignments = [
      # Product feature assignments
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": product_flag_ids.get("feature.tutor.active"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Starter"), "feature_flag_id": product_flag_ids.get("feature.mock_exams"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": product_flag_ids.get("feature.mock_exams"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": product_flag_ids.get("feature.mock_exams"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": product_flag_ids.get("feature.mock_interviews"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": product_flag_ids.get("feature.mock_interviews"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": product_flag_ids.get("feature.fenster"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": product_flag_ids.get("feature.fenster"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Starter"), "feature_flag_id": product_flag_ids.get("feature.youtube_capture"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": product_flag_ids.get("feature.youtube_capture"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": product_flag_ids.get("feature.youtube_capture"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Starter"), "feature_flag_id": product_flag_ids.get("feature.image_generation"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": product_flag_ids.get("feature.image_generation"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": product_flag_ids.get("feature.image_generation"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": product_flag_ids.get("feature.research"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": product_flag_ids.get("feature.research"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": product_flag_ids.get("feature.writing"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": product_flag_ids.get("feature.writing"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Starter"), "feature_flag_id": product_flag_ids.get("feature.ocr"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Plus"), "feature_flag_id": product_flag_ids.get("feature.ocr"), "enabled": True},
      {"subscription_tier_id": tier_ids.get("Pro"), "feature_flag_id": product_flag_ids.get("feature.ocr"), "enabled": True},
    ]

    # Enable all permission flags for all tiers
    for _tier_name, tier_id in tier_ids.items():
      for _perm_flag_key, perm_flag_id in perm_flag_ids.items():
        flag_assignments.append({"subscription_tier_id": tier_id, "feature_flag_id": perm_flag_id, "enabled": True})

    for assignment in flag_assignments:
      if assignment["subscription_tier_id"] is None or assignment["feature_flag_id"] is None:
        continue
      await connection.execute(
        text(
          "INSERT INTO subscription_tier_feature_flags "
          "(subscription_tier_id, feature_flag_id, enabled) "
          "VALUES (:subscription_tier_id, :feature_flag_id, :enabled) "
          "ON CONFLICT (subscription_tier_id, feature_flag_id) "
          "DO UPDATE SET enabled = EXCLUDED.enabled"
        ),
        assignment,
      )


async def _seed_runtime_config(connection: AsyncConnection, tier_ids: dict[str, int]) -> None:
  """Seed tier-scoped and global runtime config values."""
  if not await _ensure_columns(connection, table_name="runtime_config_values", columns=["id", "key", "scope", "subscription_tier_id", "value_json"]):
    return

  # Seed global AI model configuration (from 3c0d47535e72.py, f2c8b1e4d9aa.py)
  global_entries = [
    {"id": uuid.uuid4(), "key": "ai.research.model", "scope": "GLOBAL", "subscription_tier_id": None, "value_json": "gemini/gemini-2.0-flash"},
    {"id": uuid.uuid4(), "key": "ai.research.router_model", "scope": "GLOBAL", "subscription_tier_id": None, "value_json": "gemini/gemini-2.0-flash"},
    {"id": uuid.uuid4(), "key": "ai.planner.model", "scope": "GLOBAL", "subscription_tier_id": None, "value_json": "gemini/gemini-2.5-flash"},
    {"id": uuid.uuid4(), "key": "ai.section_builder.model", "scope": "GLOBAL", "subscription_tier_id": None, "value_json": "gemini/gemini-2.5-flash"},
  ]

  for entry in global_entries:
    entry_payload = dict(entry)
    stmt = text(
      """
      INSERT INTO runtime_config_values (id, key, scope, org_id, subscription_tier_id, user_id, value_json)
      VALUES (:id, :key, :scope, NULL, NULL, NULL, :value_json)
      ON CONFLICT (key) WHERE scope = 'GLOBAL'
      DO UPDATE SET value_json = EXCLUDED.value_json
      """
    )
    stmt = stmt.bindparams(bindparam("value_json", type_=JSONB))
    await connection.execute(stmt, entry_payload)

  if not tier_ids:
    return

  runtime_entries = [
    # Tier-specific limits
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
    {"id": uuid.uuid4(), "key": "limits.image_generations_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
    {"id": uuid.uuid4(), "key": "limits.image_generations_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 70},
    {"id": uuid.uuid4(), "key": "limits.image_generations_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 150},
    {"id": uuid.uuid4(), "key": "limits.image_generations_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 500},
    # Additional tier limits...
    {"id": uuid.uuid4(), "key": "limits.fenster_widgets_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": 0},
    {"id": uuid.uuid4(), "key": "limits.fenster_widgets_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": 0},
    {"id": uuid.uuid4(), "key": "limits.fenster_widgets_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": 40},
    {"id": uuid.uuid4(), "key": "limits.fenster_widgets_per_month", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": 120},
    # Theme settings
    {"id": uuid.uuid4(), "key": "themes.allowed", "scope": "TIER", "subscription_tier_id": tier_ids.get("Free"), "value_json": ["essential_focus"]},
    {"id": uuid.uuid4(), "key": "themes.allowed", "scope": "TIER", "subscription_tier_id": tier_ids.get("Starter"), "value_json": ["essential_focus", "cliffside_serenity"]},
    {"id": uuid.uuid4(), "key": "themes.allowed", "scope": "TIER", "subscription_tier_id": tier_ids.get("Plus"), "value_json": ["essential_focus", "oceanic_logic", "deep_forest", "stochastic_library", "cliffside_serenity"]},
    {"id": uuid.uuid4(), "key": "themes.allowed", "scope": "TIER", "subscription_tier_id": tier_ids.get("Pro"), "value_json": ["essential_focus", "oceanic_logic", "deep_forest", "stochastic_library", "cliffside_serenity"]},
  ]

  for entry in runtime_entries:
    if entry["subscription_tier_id"] is None:
      continue
    entry_payload = dict(entry)
    stmt = text(
      """
      INSERT INTO runtime_config_values (id, key, scope, subscription_tier_id, value_json)  
      VALUES (:id, :key, :scope, :subscription_tier_id, :value_json)
      ON CONFLICT (key, subscription_tier_id) WHERE scope = 'TIER'
      DO UPDATE SET value_json = EXCLUDED.value_json
      """
    )
    stmt = stmt.bindparams(bindparam("value_json", type_=JSONB))
    await connection.execute(stmt, entry_payload)


async def _seed_superadmin(connection: AsyncConnection) -> None:
  """Ensure the baseline superadmin user exists."""
  # Validate all required tables/columns exist
  users_ready = await _ensure_columns(connection, table_name="users", columns=["id", "firebase_uid", "email", "full_name", "provider", "role_id", "status", "auth_method", "onboarding_completed", "is_archived"])
  roles_ready = await _ensure_columns(connection, table_name="roles", columns=["id", "name"])
  tiers_ready = await _ensure_columns(connection, table_name="subscription_tiers", columns=["id", "name"])
  usage_ready = await _ensure_columns(connection, table_name="user_usage_metrics", columns=["user_id", "subscription_tier_id", "files_uploaded_count", "images_uploaded_count", "sections_generated_count", "research_usage_count"])

  if not (users_ready and roles_ready and tiers_ready and usage_ready):
    return

  # Resolve role and tier IDs
  role_result = await connection.execute(text("SELECT id FROM roles WHERE name = :role_name LIMIT 1"), {"role_name": "Super Admin"})
  role_id = role_result.scalar_one_or_none()
  tier_result = await connection.execute(text("SELECT id FROM subscription_tiers WHERE name = :tier_name LIMIT 1"), {"tier_name": "Pro"})
  pro_tier_id = tier_result.scalar_one_or_none()

  if role_id is None or pro_tier_id is None:
    return

  # Handle placeholder UID collisions
  placeholder_uid = SUPERADMIN_PLACEHOLDER_UID
  owner_result = await connection.execute(text("SELECT email FROM users WHERE firebase_uid = :firebase_uid LIMIT 1"), {"firebase_uid": placeholder_uid})
  owner_email = owner_result.scalar_one_or_none()
  if owner_email is not None and str(owner_email).lower() != SUPERADMIN_EMAIL:
    placeholder_uid = f"{SUPERADMIN_PLACEHOLDER_UID}-{uuid.uuid4()}"

  # Upsert superadmin user
  user_upsert = text(
    """
    INSERT INTO users (id, firebase_uid, email, full_name, provider, role_id, status, auth_method, onboarding_completed, is_archived)
    VALUES (:id, :firebase_uid, :email, :full_name, :provider, :role_id, :status, :auth_method, :onboarding_completed, :is_archived)
    ON CONFLICT (email) DO UPDATE
    SET role_id = EXCLUDED.role_id,
        status = EXCLUDED.status,
        auth_method = EXCLUDED.auth_method,
        provider = EXCLUDED.provider,
        onboarding_completed = EXCLUDED.onboarding_completed,
        full_name = COALESCE(users.full_name, EXCLUDED.full_name),
        firebase_uid = CASE
          WHEN users.firebase_uid IS NULL OR users.firebase_uid = '' OR users.firebase_uid LIKE :placeholder_uid_prefix THEN EXCLUDED.firebase_uid
          ELSE users.firebase_uid
        END
    RETURNING id
    """
  )
  user_result = await connection.execute(
    user_upsert,
    {
      "id": uuid.uuid4(),
      "firebase_uid": placeholder_uid,
      "email": SUPERADMIN_EMAIL,
      "full_name": SUPERADMIN_NAME,
      "provider": "google.com",
      "role_id": role_id,
      "status": "APPROVED",
      "auth_method": "GOOGLE_SSO",
      "onboarding_completed": True,
      "is_archived": False,
      "placeholder_uid_prefix": f"{SUPERADMIN_PLACEHOLDER_UID}%",
    },
  )
  user_id = user_result.scalar_one()

  # Ensure usage metrics exist
  usage_upsert = text(
    """
    INSERT INTO user_usage_metrics (user_id, subscription_tier_id, files_uploaded_count, images_uploaded_count, sections_generated_count, research_usage_count)
    VALUES (:user_id, :tier_id, 0, 0, 0, 0)
    ON CONFLICT (user_id) DO UPDATE
    SET subscription_tier_id = EXCLUDED.subscription_tier_id
    """
  )
  await connection.execute(usage_upsert, {"user_id": user_id, "tier_id": pro_tier_id})


async def _seed_llm_pricing(connection: AsyncConnection) -> None:
  """Seed LLM model pricing (from f7b2c1d4e6a9.py)."""
  if not await _ensure_columns(connection, table_name="llm_model_pricing", columns=["provider", "model", "input_per_1m", "output_per_1m", "is_active"]):
    return

  # Gemini model pricing in USD per 1M tokens
  pricing_rows = [
    {"provider": "gemini", "model": "gemini-2.0-flash", "input_per_1m": 0.15, "output_per_1m": 0.6},
    {"provider": "gemini", "model": "gemini-2.0-flash-lite", "input_per_1m": 0.075, "output_per_1m": 0.3},
    {"provider": "gemini", "model": "gemini-2.5-flash", "input_per_1m": 0.3, "output_per_1m": 2.5},
    {"provider": "gemini", "model": "gemini-2.5-flash-image", "input_per_1m": 0.3, "output_per_1m": 30.0},
    {"provider": "gemini", "model": "gemini-2.5-pro", "input_per_1m": 1.25, "output_per_1m": 10.0},
  ]

  for row in pricing_rows:
    await connection.execute(
      text(
        """
        INSERT INTO llm_model_pricing (provider, model, input_per_1m, output_per_1m, is_active)
        VALUES (:provider, :model, :input_per_1m, :output_per_1m, TRUE)
        ON CONFLICT (provider, model)
        DO UPDATE SET input_per_1m = EXCLUDED.input_per_1m,
                      output_per_1m = EXCLUDED.output_per_1m,
                      is_active = TRUE,
                      updated_at = now()
        """
      ),
      row,
    )


async def _seed_org_feature_flags(connection: AsyncConnection) -> None:
  """Backfill organization feature flags (from 8f2f7f3a9c11.py, c0d661232a11.py)."""
  # Check if organization_feature_flags table exists and has data to backfill
  if not await _ensure_columns(connection, table_name="organizations", columns=["id"]):
    return
  if not await _ensure_columns(connection, table_name="organization_feature_flags", columns=["org_id", "feature_flag_id", "enabled"]):
    return
  if not await _ensure_columns(connection, table_name="feature_flags", columns=["id", "key"]):
    return

  # Backfill cross-product of orgs × feature_flags
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

  # Enable all permission flags for all orgs
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


async def seed(connection: AsyncConnection) -> None:
  """Consolidated seed logic for the baseline revision."""
  # Step 1: Seed core RBAC (roles, permissions, role_permissions)
  await _seed_rbac_core(connection)

  # Step 2: Seed subscription tiers and get tier IDs
  tier_ids = await _seed_subscription_tiers(connection)

  # Step 3: Seed feature flags and tier assignments
  await _seed_feature_flags(connection, tier_ids)

  # Step 4: Seed runtime config values (global AI models + tier-specific limits)
  await _seed_runtime_config(connection, tier_ids)

  # Step 5: Seed LLM model pricing
  await _seed_llm_pricing(connection)

  # Step 6: Seed organization feature flags backfill
  await _seed_org_feature_flags(connection)

  # Step 7: Seed superadmin user
  await _seed_superadmin(connection)
