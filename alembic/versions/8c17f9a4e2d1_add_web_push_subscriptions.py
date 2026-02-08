"""Add web push subscriptions table.

Revision ID: 8c17f9a4e2d1
Revises: f97d9c8ef481
Create Date: 2026-02-07 05:15:55.382948
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_create_index, guarded_create_table, guarded_drop_index, guarded_drop_table
from sqlalchemy.dialects import postgresql

revision = "8c17f9a4e2d1"
down_revision = "f97d9c8ef481"
branch_labels = None
depends_on = None
REPAIR_SAFE = True
REPAIR_TARGETS = {
  "tables": ["web_push_subscriptions"],
  "columns": ["web_push_subscriptions.id", "web_push_subscriptions.user_id", "web_push_subscriptions.endpoint", "web_push_subscriptions.p256dh", "web_push_subscriptions.auth", "web_push_subscriptions.user_agent", "web_push_subscriptions.created_at"],
  "indexes": ["ix_web_push_subscriptions_user_id", "ux_web_push_subscriptions_endpoint"],
}


def upgrade() -> None:
  """Upgrade schema."""
  guarded_create_table(
    "web_push_subscriptions",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("endpoint", sa.Text(), nullable=False),
    sa.Column("p256dh", sa.Text(), nullable=False),
    sa.Column("auth", sa.Text(), nullable=False),
    sa.Column("user_agent", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id"),
  )
  guarded_create_index(op.f("ix_web_push_subscriptions_user_id"), "web_push_subscriptions", ["user_id"], unique=False)
  guarded_create_index("ux_web_push_subscriptions_endpoint", "web_push_subscriptions", ["endpoint"], unique=True)


def downgrade() -> None:
  """Downgrade schema."""
  guarded_drop_index("ux_web_push_subscriptions_endpoint", table_name="web_push_subscriptions")
  guarded_drop_index(op.f("ix_web_push_subscriptions_user_id"), table_name="web_push_subscriptions")
  guarded_drop_table("web_push_subscriptions")
