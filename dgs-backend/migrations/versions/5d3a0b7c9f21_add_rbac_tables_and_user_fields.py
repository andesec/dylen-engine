"""Add RBAC tables and user fields with idempotent safeguards.

Revision ID: 5d3a0b7c9f21
Revises: 4c880c225edd
Create Date: 2026-01-25 00:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "5d3a0b7c9f21"
down_revision: str | None = "8b4f5e7c8d9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SUPER_ADMIN_ROLE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_ADMIN_ROLE_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
ORG_MEMBER_ROLE_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
RBAC_MANAGE_PERMISSION_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
USER_MANAGE_PERMISSION_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _table_exists(existing_tables: set[str], table_name: str) -> bool:
  """Check cached table names so migrations can be rerun safely."""
  # Reuse cached table names to avoid duplicate table errors.
  return table_name in existing_tables


def _get_columns(inspector, table_name: str, existing_tables: set[str]) -> set[str]:
  """Load column names for a table only when it exists."""
  # Skip column inspection when the table does not exist.
  if table_name not in existing_tables:
    return set()
  return {str(col.get("name")) for col in inspector.get_columns(table_name) if col.get("name")}


def _index_exists(inspector, table_name: str, index_name: str, existing_tables: set[str]) -> bool:
  """Detect indexes by name to avoid duplicate index errors."""
  # Skip index inspection when the table does not exist.
  if table_name not in existing_tables:
    return False
  return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _foreign_key_exists(inspector, table_name: str, fk_name: str, existing_tables: set[str]) -> bool:
  """Detect foreign keys by name to avoid duplicate constraint errors."""
  # Skip foreign key inspection when the table does not exist.
  if table_name not in existing_tables:
    return False
  return any(fk.get("name") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
  """Apply RBAC schema changes while handling pre-existing tables."""

  # Ensure enum types exist before columns reference them.
  # We use explicit SQL block to avoid race conditions/reflection issues with asyncpg.
  op.execute("DO $$ BEGIN CREATE TYPE role_level AS ENUM ('GLOBAL', 'TENANT'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
  op.execute("DO $$ BEGIN CREATE TYPE user_status AS ENUM ('PENDING', 'APPROVED', 'DISABLED'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
  op.execute("DO $$ BEGIN CREATE TYPE auth_method AS ENUM ('GOOGLE_SSO', 'NATIVE'); EXCEPTION WHEN duplicate_object THEN null; END $$;")

  role_level_enum = sa.Enum("GLOBAL", "TENANT", name="role_level")
  user_status_enum = sa.Enum("PENDING", "APPROVED", "DISABLED", name="user_status")
  auth_method_enum = sa.Enum("GOOGLE_SSO", "NATIVE", name="auth_method")

  # Inspect existing schema to keep migration idempotent.
  inspector = inspect(op.get_bind())
  existing_tables = set(inspector.get_table_names())
  user_columns = _get_columns(inspector, "users", existing_tables)

  # Create organization storage for tenant isolation.
  if not _table_exists(existing_tables, "organizations"):
    # Create organizations when they are missing.
    op.create_table(
      "organizations",
      sa.Column("id", sa.UUID(), nullable=False),
      sa.Column("name", sa.String(), nullable=False),
      sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
      sa.PrimaryKeyConstraint("id"),
      sa.UniqueConstraint("name"),
    )
    existing_tables.add("organizations")

  # Create RBAC tables for roles and permissions.
  if not _table_exists(existing_tables, "roles"):
    # Create roles when they are missing.
    op.create_table(
      "roles",
      sa.Column("id", sa.UUID(), nullable=False),
      sa.Column("name", sa.String(), nullable=False),
      sa.Column("level", role_level_enum, nullable=False),
      sa.Column("description", sa.Text(), nullable=True),
      sa.PrimaryKeyConstraint("id"),
      sa.UniqueConstraint("name"),
    )
    existing_tables.add("roles")

  if not _table_exists(existing_tables, "permissions"):
    # Create permissions when they are missing.
    op.create_table(
      "permissions",
      sa.Column("id", sa.UUID(), nullable=False),
      sa.Column("slug", sa.String(), nullable=False),
      sa.Column("display_name", sa.String(), nullable=False),
      sa.Column("description", sa.Text(), nullable=True),
      sa.PrimaryKeyConstraint("id"),
      sa.UniqueConstraint("slug"),
    )
    existing_tables.add("permissions")

  if not _table_exists(existing_tables, "role_permissions"):
    # Create join table when it is missing.
    op.create_table(
      "role_permissions",
      sa.Column("role_id", sa.UUID(), nullable=False),
      sa.Column("permission_id", sa.UUID(), nullable=False),
      sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"]),
      sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
      sa.PrimaryKeyConstraint("role_id", "permission_id"),
    )
    existing_tables.add("role_permissions")

  # Seed baseline roles and permissions for admin workflows.
  if _table_exists(existing_tables, "roles"):
    # Use upserts to avoid conflicts when seed rows already exist.
    op.execute(
      sa.text("INSERT INTO roles (id, name, level, description) VALUES (:id, :name, CAST(:level AS role_level), :description) ON CONFLICT (id) DO NOTHING").bindparams(
        id=SUPER_ADMIN_ROLE_ID, name="Super Admin", level="GLOBAL", description="Global administrative access."
      )
    )
    op.execute(
      sa.text("INSERT INTO roles (id, name, level, description) VALUES (:id, :name, CAST(:level AS role_level), :description) ON CONFLICT (id) DO NOTHING").bindparams(
        id=ORG_ADMIN_ROLE_ID, name="Org Admin", level="TENANT", description="Organization administrative access."
      )
    )
    op.execute(
      sa.text("INSERT INTO roles (id, name, level, description) VALUES (:id, :name, CAST(:level AS role_level), :description) ON CONFLICT (id) DO NOTHING").bindparams(
        id=ORG_MEMBER_ROLE_ID, name="Org Member", level="TENANT", description="Standard organization access."
      )
    )

  if _table_exists(existing_tables, "permissions"):
    # Use upserts to avoid conflicts when seed rows already exist.
    op.execute(
      sa.text("INSERT INTO permissions (id, slug, display_name, description) VALUES (:id, :slug, :display_name, :description) ON CONFLICT (id) DO NOTHING").bindparams(
        id=RBAC_MANAGE_PERMISSION_ID, slug="rbac:manage", display_name="Manage RBAC", description="Create roles and assign permissions."
      )
    )
    op.execute(
      sa.text("INSERT INTO permissions (id, slug, display_name, description) VALUES (:id, :slug, :display_name, :description) ON CONFLICT (id) DO NOTHING").bindparams(
        id=USER_MANAGE_PERMISSION_ID, slug="user:manage", display_name="Manage Users", description="List users and update roles/statuses."
      )
    )

  if _table_exists(existing_tables, "role_permissions"):
    # Use upserts to avoid conflicts when join rows already exist.
    op.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:role_id, :permission_id) ON CONFLICT (role_id, permission_id) DO NOTHING").bindparams(role_id=SUPER_ADMIN_ROLE_ID, permission_id=RBAC_MANAGE_PERMISSION_ID))
    op.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:role_id, :permission_id) ON CONFLICT (role_id, permission_id) DO NOTHING").bindparams(role_id=SUPER_ADMIN_ROLE_ID, permission_id=USER_MANAGE_PERMISSION_ID))
    op.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:role_id, :permission_id) ON CONFLICT (role_id, permission_id) DO NOTHING").bindparams(role_id=ORG_ADMIN_ROLE_ID, permission_id=USER_MANAGE_PERMISSION_ID))

  # Add new RBAC columns to users for role/status tracking.
  if "users" in existing_tables:
    # Add columns only when missing to avoid duplicate column errors.
    if "role_id" not in user_columns:
      op.add_column("users", sa.Column("role_id", sa.UUID(), nullable=True))
      user_columns.add("role_id")

    if "org_id" not in user_columns:
      op.add_column("users", sa.Column("org_id", sa.UUID(), nullable=True))
      user_columns.add("org_id")

    if "status" not in user_columns:
      op.add_column("users", sa.Column("status", user_status_enum, nullable=True))
      user_columns.add("status")

    if "auth_method" not in user_columns:
      op.add_column("users", sa.Column("auth_method", auth_method_enum, nullable=True))
      user_columns.add("auth_method")

    # Add foreign keys only when missing to avoid duplicate constraint errors.
    if not _foreign_key_exists(inspector, "users", "fk_users_role_id_roles", existing_tables):
      op.create_foreign_key("fk_users_role_id_roles", "users", "roles", ["role_id"], ["id"])

    if not _foreign_key_exists(inspector, "users", "fk_users_org_id_organizations", existing_tables):
      op.create_foreign_key("fk_users_org_id_organizations", "users", "organizations", ["org_id"], ["id"])

    # Add the org index when missing to keep queries fast.
    if not _index_exists(inspector, "users", op.f("ix_users_org_id"), existing_tables):
      op.create_index(op.f("ix_users_org_id"), "users", ["org_id"], unique=False)

  # Backfill role and status values to keep existing users working.
  if "users" in existing_tables:
    # Update role_id from legacy is_admin flag when present.
    if "is_admin" in user_columns and "role_id" in user_columns:
      op.execute(sa.text("UPDATE users SET role_id = :role_id WHERE is_admin = true").bindparams(role_id=SUPER_ADMIN_ROLE_ID))

    # Ensure every user has a role_id after the migration.
    if "role_id" in user_columns:
      op.execute(sa.text("UPDATE users SET role_id = :role_id WHERE role_id IS NULL").bindparams(role_id=ORG_MEMBER_ROLE_ID))

    # Update status from legacy is_approved flag when present.
    if "is_approved" in user_columns and "status" in user_columns:
      op.execute(sa.text("UPDATE users SET status = 'APPROVED' WHERE is_approved = true"))

    # Default pending status when missing.
    if "status" in user_columns:
      op.execute(sa.text("UPDATE users SET status = 'PENDING' WHERE status IS NULL"))

    # Default auth_method when missing.
    if "auth_method" in user_columns:
      op.execute(sa.text("UPDATE users SET auth_method = 'GOOGLE_SSO' WHERE auth_method IS NULL"))

  # Lock required columns once defaults are in place.
  if "users" in existing_tables:
    # Only enforce NOT NULL when the column exists and has no nulls.
    if "role_id" in user_columns:
      null_role_count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM users WHERE role_id IS NULL")).scalar()
      if null_role_count == 0:
        op.alter_column("users", "role_id", nullable=False)

    if "status" in user_columns:
      null_status_count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM users WHERE status IS NULL")).scalar()
      if null_status_count == 0:
        op.alter_column("users", "status", nullable=False)

    if "auth_method" in user_columns:
      null_auth_count = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM users WHERE auth_method IS NULL")).scalar()
      if null_auth_count == 0:
        op.alter_column("users", "auth_method", nullable=False)


def downgrade() -> None:
  """Reverse RBAC changes while preserving existing data where possible."""
  # Relax and remove new user columns before dropping RBAC tables.
  op.drop_index(op.f("ix_users_org_id"), table_name="users")
  op.drop_constraint("fk_users_org_id_organizations", "users", type_="foreignkey")
  op.drop_constraint("fk_users_role_id_roles", "users", type_="foreignkey")
  op.drop_column("users", "auth_method")
  op.drop_column("users", "status")
  op.drop_column("users", "org_id")
  op.drop_column("users", "role_id")

  # Drop RBAC tables in reverse dependency order.
  op.drop_table("role_permissions")
  op.drop_table("permissions")
  op.drop_table("roles")
  op.drop_table("organizations")

  # Drop enum types after all dependent columns are removed.
  auth_method_enum = sa.Enum("GOOGLE_SSO", "NATIVE", name="auth_method")
  auth_method_enum.drop(op.get_bind(), checkfirst=True)
  user_status_enum = sa.Enum("PENDING", "APPROVED", "DISABLED", name="user_status")
  user_status_enum.drop(op.get_bind(), checkfirst=True)
  role_level_enum = sa.Enum("GLOBAL", "TENANT", name="role_level")
  role_level_enum.drop(op.get_bind(), checkfirst=True)
