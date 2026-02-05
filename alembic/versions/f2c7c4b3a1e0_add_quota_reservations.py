"""Add quota reservations and reserved counters.

Revision ID: f2c7c4b3a1e0
Revises: 3a941f60baac
Create Date: 2026-02-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_add_column, guarded_create_index, guarded_create_table, guarded_drop_column, guarded_drop_index, guarded_drop_table
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f2c7c4b3a1e0"
down_revision = "3a941f60baac"
branch_labels = None
depends_on = None


def upgrade() -> None:
  """Upgrade schema."""
  guarded_add_column("user_quota_buckets", sa.Column("reserved", sa.BigInteger(), server_default="0", nullable=False))
  guarded_create_table(
    "user_quota_reservations",
    sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("metric_key", sa.String(), nullable=False),
    sa.Column("period", postgresql.ENUM("WEEK", "MONTH", name="quota_period", create_type=False), nullable=False),
    sa.Column("period_start", sa.Date(), nullable=False),
    sa.Column("quantity", sa.BigInteger(), server_default="1", nullable=False),
    sa.Column("job_id", sa.String(), nullable=False),
    sa.Column("section_index", sa.Integer(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    sa.PrimaryKeyConstraint("id"),
    sa.UniqueConstraint("user_id", "metric_key", "period", "period_start", "job_id", "section_index", name="ux_quota_reservation_key"),
  )
  guarded_create_index(op.f("ix_user_quota_reservations_user_id"), "user_quota_reservations", ["user_id"], unique=False)
  guarded_create_index(op.f("ix_user_quota_reservations_metric_key"), "user_quota_reservations", ["metric_key"], unique=False)
  guarded_create_index(op.f("ix_user_quota_reservations_job_id"), "user_quota_reservations", ["job_id"], unique=False)


def downgrade() -> None:
  """Downgrade schema."""
  guarded_drop_index(op.f("ix_user_quota_reservations_job_id"), table_name="user_quota_reservations")
  guarded_drop_index(op.f("ix_user_quota_reservations_metric_key"), table_name="user_quota_reservations")
  guarded_drop_index(op.f("ix_user_quota_reservations_user_id"), table_name="user_quota_reservations")
  guarded_drop_table("user_quota_reservations")
  guarded_drop_column("user_quota_buckets", "reserved")
