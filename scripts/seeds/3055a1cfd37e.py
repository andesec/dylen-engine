"""Seed core RBAC and subscription tiers for the baseline migration."""

from __future__ import annotations

import uuid

from sqlalchemy import text
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
        "name2": "Org Admin",
        "level2": "TENANT",
        "desc2": "Organization administrator.",
        "id3": role_org_member_id,
        "name3": "Org Member",
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
    columns=["name", "max_file_upload_kb", "highest_lesson_depth", "max_sections_per_lesson", "file_upload_quota", "image_upload_quota", "gen_sections_quota", "research_quota", "coach_mode_enabled", "coach_voice_tier"],
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
          coach_mode_enabled,
          coach_voice_tier
        )
        VALUES
          (:name1, :mfu1, :depth1, :sections1, :fuq1, :iuq1, :gsq1, :rq1, :coach1, :voice1),
          (:name2, :mfu2, :depth2, :sections2, :fuq2, :iuq2, :gsq2, :rq2, :coach2, :voice2),
          (:name3, :mfu3, :depth3, :sections3, :fuq3, :iuq3, :gsq3, :rq3, :coach3, :voice3)
        ON CONFLICT (name) DO UPDATE
        SET max_file_upload_kb = EXCLUDED.max_file_upload_kb,
            highest_lesson_depth = EXCLUDED.highest_lesson_depth,
            max_sections_per_lesson = EXCLUDED.max_sections_per_lesson,
            file_upload_quota = EXCLUDED.file_upload_quota,
            image_upload_quota = EXCLUDED.image_upload_quota,
            gen_sections_quota = EXCLUDED.gen_sections_quota,
            research_quota = EXCLUDED.research_quota,
            coach_mode_enabled = EXCLUDED.coach_mode_enabled,
            coach_voice_tier = EXCLUDED.coach_voice_tier
        """
      ),
      {
        "name1": "Free",
        "mfu1": 512,
        "depth1": "highlights",
        "sections1": 2,
        "fuq1": 0,
        "iuq1": 0,
        "gsq1": 20,
        "rq1": None,
        "coach1": False,
        "voice1": "none",
        "name2": "Plus",
        "mfu2": 1024,
        "depth2": "detailed",
        "sections2": 6,
        "fuq2": 5,
        "iuq2": 5,
        "gsq2": 100,
        "rq2": None,
        "coach2": True,
        "voice2": "device",
        "name3": "Pro",
        "mfu3": 2048,
        "depth3": "training",
        "sections3": 10,
        "fuq3": 10,
        "iuq3": 10,
        "gsq3": 250,
        "rq3": None,
        "coach3": True,
        "voice3": "premium",
      },
    )
