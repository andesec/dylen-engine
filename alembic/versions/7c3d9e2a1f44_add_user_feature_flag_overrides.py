"""Add per-user feature flag promo overrides.

Revision ID: 7c3d9e2a1f44
Revises: 5e2d7f94ab31
Create Date: 2026-02-09 22:15:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from app.core.migration_guards import guarded_create_index, guarded_create_table
from sqlalchemy.dialects import postgresql

revision = "7c3d9e2a1f44"
down_revision = "5e2d7f94ab31"
branch_labels = None
depends_on = None

REPAIR_TARGETS = {
  "tables": ["user_feature_flag_overrides"],
  "columns": [
    "user_feature_flag_overrides.id",
    "user_feature_flag_overrides.user_id",
    "user_feature_flag_overrides.feature_flag_id",
    "user_feature_flag_overrides.enabled",
    "user_feature_flag_overrides.starts_at",
    "user_feature_flag_overrides.expires_at",
    "user_feature_flag_overrides.updated_at",
  ],
  "indexes": ["ix_user_feature_flag_overrides_user_id", "ix_user_feature_flag_overrides_feature_flag_id", "ix_user_feature_flag_overrides_user_window"],
  "constraints": ["ux_user_feature_flag_overrides_user_flag"],
}


def upgrade() -> None:
  """Upgrade schema."""
  guarded_create_table(
    "user_feature_flag_overrides",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("feature_flag_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("enabled", sa.Boolean(), nullable=False),
    sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.ForeignKeyConstraint(["feature_flag_id"], ["feature_flags.id"]),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    sa.PrimaryKeyConstraint("id"),
    sa.UniqueConstraint("user_id", "feature_flag_id", name="ux_user_feature_flag_overrides_user_flag"),
  )
  guarded_create_index("ix_user_feature_flag_overrides_user_id", "user_feature_flag_overrides", ["user_id"], unique=False)
  guarded_create_index("ix_user_feature_flag_overrides_feature_flag_id", "user_feature_flag_overrides", ["feature_flag_id"], unique=False)
  guarded_create_index("ix_user_feature_flag_overrides_user_window", "user_feature_flag_overrides", ["user_id", "starts_at", "expires_at"], unique=False)


def downgrade() -> None:
  """Downgrade schema."""
  # Keep downgrade non-destructive for production safety.
  return None
