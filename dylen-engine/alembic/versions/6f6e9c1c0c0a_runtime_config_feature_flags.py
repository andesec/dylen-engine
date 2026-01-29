"""runtime_config_feature_flags

Revision ID: 6f6e9c1c0c0a
Revises: f22845381c3c
Create Date: 2026-01-29 04:55:00.000000

"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f6e9c1c0c0a"
down_revision: str | Sequence[str] | None = "f22845381c3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  op.create_table(
    "feature_flags",
    sa.Column("id", sa.Uuid(), nullable=False),
    sa.Column("key", sa.String(), nullable=False),
    sa.Column("description", sa.Text(), nullable=True),
    sa.Column("default_enabled", sa.Boolean(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.PrimaryKeyConstraint("id"),
    sa.UniqueConstraint("key"),
  )
  op.create_index(op.f("ix_feature_flags_key"), "feature_flags", ["key"], unique=False)

  op.create_table(
    "organization_feature_flags",
    sa.Column("org_id", sa.Uuid(), nullable=False),
    sa.Column("feature_flag_id", sa.Uuid(), nullable=False),
    sa.Column("enabled", sa.Boolean(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.ForeignKeyConstraint(["feature_flag_id"], ["feature_flags.id"]),
    sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
    sa.PrimaryKeyConstraint("org_id", "feature_flag_id"),
  )
  op.create_table(
    "subscription_tier_feature_flags",
    sa.Column("subscription_tier_id", sa.Integer(), nullable=False),
    sa.Column("feature_flag_id", sa.Uuid(), nullable=False),
    sa.Column("enabled", sa.Boolean(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.ForeignKeyConstraint(["feature_flag_id"], ["feature_flags.id"]),
    sa.ForeignKeyConstraint(["subscription_tier_id"], ["subscription_tiers.id"]),
    sa.PrimaryKeyConstraint("subscription_tier_id", "feature_flag_id"),
  )

  op.create_table(
    "runtime_config_values",
    sa.Column("id", sa.Uuid(), nullable=False),
    sa.Column("key", sa.String(), nullable=False),
    sa.Column("scope", sa.Enum("GLOBAL", "TIER", "TENANT", name="runtime_config_scope"), nullable=False),
    sa.Column("org_id", sa.Uuid(), nullable=True),
    sa.Column("subscription_tier_id", sa.Integer(), nullable=True),
    sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
    sa.ForeignKeyConstraint(["subscription_tier_id"], ["subscription_tiers.id"]),
    sa.PrimaryKeyConstraint("id"),
  )
  op.create_index(op.f("ix_runtime_config_values_key"), "runtime_config_values", ["key"], unique=False)
  op.create_index(op.f("ix_runtime_config_values_org_id"), "runtime_config_values", ["org_id"], unique=False)
  op.create_index(op.f("ix_runtime_config_values_scope"), "runtime_config_values", ["scope"], unique=False)
  op.create_index(op.f("ix_runtime_config_values_subscription_tier_id"), "runtime_config_values", ["subscription_tier_id"], unique=False)
  op.create_index("ux_runtime_config_values_global", "runtime_config_values", ["key"], unique=True, postgresql_where=sa.text("scope = 'GLOBAL'"))
  op.create_index("ux_runtime_config_values_tenant", "runtime_config_values", ["key", "org_id"], unique=True, postgresql_where=sa.text("scope = 'TENANT'"))
  op.create_index("ux_runtime_config_values_tier", "runtime_config_values", ["key", "subscription_tier_id"], unique=True, postgresql_where=sa.text("scope = 'TIER'"))

  # Seed permissions and roles for config/flag administration.
  role_super_admin_id = uuid.UUID("3e56ebfc-1d62-42cb-a920-ab6e916e58bf")
  role_org_admin_id = uuid.UUID("102d6fab-322c-48f8-a8f8-0d9e5eb52aa6")
  role_admin_id = uuid.UUID("9a0a40f4-4c6e-4a47-8e93-9e2e2d8c2f60")
  roles_table = sa.table("roles", sa.column("id"), sa.column("name"), sa.column("level"), sa.column("description"))
  permissions_table = sa.table("permissions", sa.column("id"), sa.column("slug"), sa.column("display_name"), sa.column("description"))
  role_permissions_table = sa.table("role_permissions", sa.column("role_id"), sa.column("permission_id"))

  permission_config_read_id = uuid.UUID("a9b945d1-1f04-4b1a-8ab7-22d9ad5cf5d1")
  permission_config_write_global_id = uuid.UUID("2f9e57d5-9d5e-43d0-842e-5bcb7d7d8e0c")
  permission_config_write_tier_id = uuid.UUID("99f9e8b8-2e9d-4a53-9f15-2f49b7e7f2f5")
  permission_config_write_org_id = uuid.UUID("1dd1dc11-7a16-48f6-9cc5-2f4b54f3e361")
  permission_flags_read_id = uuid.UUID("c3c6b7a5-5a6f-4a20-b4a6-1e7d6f13e5a2")
  permission_flags_write_global_id = uuid.UUID("1a9f1e62-6c1d-4e71-8f52-2c4b9a0a2b9c")
  permission_flags_write_tier_id = uuid.UUID("5c0d5b18-7c4a-4d34-8f8b-1a0b8b1d8a0c")
  permission_flags_write_org_id = uuid.UUID("c0a1a5f1-9e5b-4b2e-9b7b-7b3f1e2c0a1b")

  op.execute(insert(roles_table).values([{"id": role_admin_id, "name": "Admin", "level": "GLOBAL", "description": "Global administrator (non-super)."}]).on_conflict_do_nothing(index_elements=["name"]))

  op.execute(
    insert(permissions_table)
    .values(
      [
        {"id": permission_config_read_id, "slug": "config:read", "display_name": "Read Config", "description": "Read runtime configuration values."},
        {"id": permission_config_write_global_id, "slug": "config:write_global", "display_name": "Write Global Config", "description": "Update global runtime configuration defaults."},
        {"id": permission_config_write_tier_id, "slug": "config:write_tier", "display_name": "Write Tier Config", "description": "Update subscription tier runtime configuration defaults."},
        {"id": permission_config_write_org_id, "slug": "config:write_org", "display_name": "Write Org Config", "description": "Update tenant runtime configuration overrides."},
        {"id": permission_flags_read_id, "slug": "flags:read", "display_name": "Read Feature Flags", "description": "Read feature flags and overrides."},
        {"id": permission_flags_write_global_id, "slug": "flags:write_global", "display_name": "Write Global Feature Flags", "description": "Create and update feature flag defaults."},
        {"id": permission_flags_write_tier_id, "slug": "flags:write_tier", "display_name": "Write Tier Feature Flags", "description": "Update subscription tier feature flag defaults."},
        {"id": permission_flags_write_org_id, "slug": "flags:write_org", "display_name": "Write Org Feature Flags", "description": "Update tenant feature flag overrides."},
      ]
    )
    .on_conflict_do_nothing(index_elements=["slug"])
  )

  # Grant super admin full control.
  op.execute(
    insert(role_permissions_table)
    .values(
      [
        {"role_id": role_super_admin_id, "permission_id": permission_config_read_id},
        {"role_id": role_super_admin_id, "permission_id": permission_config_write_global_id},
        {"role_id": role_super_admin_id, "permission_id": permission_config_write_tier_id},
        {"role_id": role_super_admin_id, "permission_id": permission_config_write_org_id},
        {"role_id": role_super_admin_id, "permission_id": permission_flags_read_id},
        {"role_id": role_super_admin_id, "permission_id": permission_flags_write_global_id},
        {"role_id": role_super_admin_id, "permission_id": permission_flags_write_tier_id},
        {"role_id": role_super_admin_id, "permission_id": permission_flags_write_org_id},
      ]
    )
    .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
  )

  # Grant admin global + tier editing without super-only permissions like user management.
  op.execute(
    insert(role_permissions_table)
    .values(
      [
        {"role_id": role_admin_id, "permission_id": permission_config_read_id},
        {"role_id": role_admin_id, "permission_id": permission_config_write_global_id},
        {"role_id": role_admin_id, "permission_id": permission_config_write_tier_id},
        {"role_id": role_admin_id, "permission_id": permission_config_write_org_id},
        {"role_id": role_admin_id, "permission_id": permission_flags_read_id},
        {"role_id": role_admin_id, "permission_id": permission_flags_write_global_id},
        {"role_id": role_admin_id, "permission_id": permission_flags_write_tier_id},
        {"role_id": role_admin_id, "permission_id": permission_flags_write_org_id},
      ]
    )
    .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
  )

  # Grant org admin tenant-scoped editing.
  op.execute(
    insert(role_permissions_table)
    .values(
      [
        {"role_id": role_org_admin_id, "permission_id": permission_config_read_id},
        {"role_id": role_org_admin_id, "permission_id": permission_config_write_org_id},
        {"role_id": role_org_admin_id, "permission_id": permission_flags_read_id},
        {"role_id": role_org_admin_id, "permission_id": permission_flags_write_org_id},
      ]
    )
    .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])
  )

  # Seed initial feature flags and tier defaults.
  feature_flags_table = sa.table("feature_flags", sa.column("id"), sa.column("key"), sa.column("description"), sa.column("default_enabled"))
  op.execute(
    insert(feature_flags_table)
    .values(
      [
        {"id": uuid.UUID("f6f8a65c-8d55-4ed0-8f0d-7b0b3a7c6c01"), "key": "feature.fenster", "description": "Enable Fenster widget generation features.", "default_enabled": False},
        {"id": uuid.UUID("4b4aeb5b-5d5b-4e2b-8b7b-7e6e5c4d3c02"), "key": "feature.research", "description": "Enable research agent features.", "default_enabled": False},
        {"id": uuid.UUID("2c2b1a0f-1e2d-4c3b-9a8b-7c6d5e4f3a03"), "key": "feature.notifications.email", "description": "Enable outbound email notifications.", "default_enabled": False},
        {"id": uuid.UUID("1a0f2b3c-4d5e-6f70-8a9b-0c1d2e3f4a04"), "key": "feature.ocr", "description": "Enable OCR endpoints and UI.", "default_enabled": True},
        {"id": uuid.UUID("0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a05"), "key": "feature.writing", "description": "Enable writing-check endpoints and UI.", "default_enabled": True},
      ]
    )
    .on_conflict_do_nothing(index_elements=["key"])
  )

  bind = op.get_bind()
  tiers_result = bind.execute(sa.text("select id, name from subscription_tiers where name in ('Plus', 'Pro')"))
  tiers = {row[1]: int(row[0]) for row in tiers_result.fetchall()}
  if tiers:
    tier_flags_table = sa.table("subscription_tier_feature_flags", sa.column("subscription_tier_id"), sa.column("feature_flag_id"), sa.column("enabled"))
    fenster_flag_id = uuid.UUID("f6f8a65c-8d55-4ed0-8f0d-7b0b3a7c6c01")
    research_flag_id = uuid.UUID("4b4aeb5b-5d5b-4e2b-8b7b-7e6e5c4d3c02")
    rows: list[dict[str, object]] = []
    if tiers.get("Plus") is not None:
      rows.append({"subscription_tier_id": tiers["Plus"], "feature_flag_id": fenster_flag_id, "enabled": True})
      rows.append({"subscription_tier_id": tiers["Plus"], "feature_flag_id": research_flag_id, "enabled": True})
    if tiers.get("Pro") is not None:
      rows.append({"subscription_tier_id": tiers["Pro"], "feature_flag_id": fenster_flag_id, "enabled": True})
      rows.append({"subscription_tier_id": tiers["Pro"], "feature_flag_id": research_flag_id, "enabled": True})
    op.execute(insert(tier_flags_table).values(rows).on_conflict_do_nothing(index_elements=["subscription_tier_id", "feature_flag_id"]))


def downgrade() -> None:
  """Downgrade schema."""
  op.drop_index("ux_runtime_config_values_tier", table_name="runtime_config_values")
  op.drop_index("ux_runtime_config_values_tenant", table_name="runtime_config_values")
  op.drop_index("ux_runtime_config_values_global", table_name="runtime_config_values")
  op.drop_index(op.f("ix_runtime_config_values_subscription_tier_id"), table_name="runtime_config_values")
  op.drop_index(op.f("ix_runtime_config_values_scope"), table_name="runtime_config_values")
  op.drop_index(op.f("ix_runtime_config_values_org_id"), table_name="runtime_config_values")
  op.drop_index(op.f("ix_runtime_config_values_key"), table_name="runtime_config_values")
  op.drop_table("runtime_config_values")
  op.drop_table("subscription_tier_feature_flags")
  op.drop_table("organization_feature_flags")
  op.drop_index(op.f("ix_feature_flags_key"), table_name="feature_flags")
  op.drop_table("feature_flags")

  # Drop the enum created for runtime config scope.
  op.execute(sa.text("drop type if exists runtime_config_scope"))
