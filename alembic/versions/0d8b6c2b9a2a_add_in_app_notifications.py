"""Add in-app notifications table.

Revision ID: 0d8b6c2b9a2a
Revises: f2c7c4b3a1e0
Create Date: 2026-02-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_create_index, guarded_create_table, guarded_drop_index, guarded_drop_table
from sqlalchemy.dialects import postgresql

revision = "0d8b6c2b9a2a"
down_revision = "f2c7c4b3a1e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
  """Upgrade schema."""
  guarded_create_table(
    "notifications",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("template_id", sa.String(), nullable=False),
    sa.Column("title", sa.String(), nullable=False),
    sa.Column("body", sa.Text(), nullable=False),
    sa.Column("data_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column("read", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    sa.PrimaryKeyConstraint("id"),
  )
  guarded_create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
  guarded_create_index(op.f("ix_notifications_template_id"), "notifications", ["template_id"], unique=False)


def downgrade() -> None:
  """Downgrade schema."""
  guarded_drop_index(op.f("ix_notifications_template_id"), table_name="notifications")
  guarded_drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
  guarded_drop_table("notifications")
