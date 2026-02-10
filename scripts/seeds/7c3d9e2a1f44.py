"""Seed data for migration 7c3d9e2a1f44."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_SUPERADMIN_EMAIL = "dylen.app@gmail.com"
_SUPERADMIN_PLACEHOLDER_UID = "bootstrap-dylen-superadmin"
_SUPERADMIN_NAME = "Dylen Superadmin"


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
  """Ensure the baseline superadmin user exists in Postgres."""
  # Validate all required tables/columns exist before attempting superadmin upserts.
  users_ready = await _ensure_columns(connection, table_name="users", columns=["id", "firebase_uid", "email", "full_name", "provider", "role_id", "status", "auth_method", "onboarding_completed"])
  roles_ready = await _ensure_columns(connection, table_name="roles", columns=["id", "name"])
  tiers_ready = await _ensure_columns(connection, table_name="subscription_tiers", columns=["id", "name"])
  usage_ready = await _ensure_columns(connection, table_name="user_usage_metrics", columns=["user_id", "subscription_tier_id", "files_uploaded_count", "images_uploaded_count", "sections_generated_count", "research_usage_count"])
  if not users_ready or not roles_ready or not tiers_ready or not usage_ready:
    return

  # Resolve canonical role and tier identifiers used by the superadmin account.
  role_result = await connection.execute(text("SELECT id FROM roles WHERE name = :role_name LIMIT 1"), {"role_name": "Super Admin"})
  role_id = role_result.scalar_one_or_none()
  tier_result = await connection.execute(text("SELECT id FROM subscription_tiers WHERE name = :tier_name LIMIT 1"), {"tier_name": "Pro"})
  pro_tier_id = tier_result.scalar_one_or_none()
  if role_id is None or pro_tier_id is None:
    return

  # Avoid unique-key collisions if another row already consumed the placeholder UID.
  placeholder_uid = _SUPERADMIN_PLACEHOLDER_UID
  owner_result = await connection.execute(text("SELECT email FROM users WHERE firebase_uid = :firebase_uid LIMIT 1"), {"firebase_uid": placeholder_uid})
  owner_email = owner_result.scalar_one_or_none()
  if owner_email is not None and str(owner_email).lower() != _SUPERADMIN_EMAIL:
    placeholder_uid = f"{_SUPERADMIN_PLACEHOLDER_UID}-{uuid.uuid4()}"

  # Upsert the superadmin DB identity using a placeholder Firebase UID until startup reconciliation.
  user_upsert = text(
    """
    INSERT INTO users (id, firebase_uid, email, full_name, provider, role_id, status, auth_method, onboarding_completed)
    VALUES (:id, :firebase_uid, :email, :full_name, :provider, :role_id, :status, :auth_method, :onboarding_completed)
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
      "email": _SUPERADMIN_EMAIL,
      "full_name": _SUPERADMIN_NAME,
      "provider": "google.com",
      "role_id": role_id,
      "status": "APPROVED",
      "auth_method": "GOOGLE_SSO",
      "onboarding_completed": True,
      "placeholder_uid_prefix": f"{_SUPERADMIN_PLACEHOLDER_UID}%",
    },
  )
  user_id = user_result.scalar_one()

  # Ensure usage metrics exist and enforce the Pro tier baseline for superadmin access.
  usage_upsert = text(
    """
    INSERT INTO user_usage_metrics (user_id, subscription_tier_id, files_uploaded_count, images_uploaded_count, sections_generated_count, research_usage_count)
    VALUES (:user_id, :tier_id, 0, 0, 0, 0)
    ON CONFLICT (user_id) DO UPDATE
    SET subscription_tier_id = EXCLUDED.subscription_tier_id
    """
  )
  await connection.execute(usage_upsert, {"user_id": user_id, "tier_id": pro_tier_id})
