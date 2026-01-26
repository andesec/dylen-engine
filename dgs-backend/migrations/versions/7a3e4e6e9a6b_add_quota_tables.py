"""Add subscription tiers and quota tracking tables.

Revision ID: 7a3e4e6e9a6b
Revises: 6b7a7c3c1f5a
Create Date: 2026-01-24
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7a3e4e6e9a6b"
down_revision: str | Sequence[str] | None = "6b7a7c3c1f5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  op.create_table(
    "subscription_tiers",
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
    sa.Column("name", sa.String(), unique=True, nullable=False),
    sa.Column("max_file_upload_kb", sa.Integer(), nullable=True),
    sa.Column("highest_lesson_depth", sa.Enum("highlights", "detailed", "training", name="lesson_depth"), nullable=True),
    sa.Column("max_sections_per_lesson", sa.Integer(), nullable=True),
    sa.Column("file_upload_quota", sa.Integer(), nullable=True),
    sa.Column("image_upload_quota", sa.Integer(), nullable=True),
    sa.Column("gen_sections_quota", sa.Integer(), nullable=True),
    sa.Column("coach_mode_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("coach_voice_tier", sa.String(), nullable=True),
  )

  op.create_table(
    "user_tier_overrides",
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("max_file_upload_kb", sa.Integer(), nullable=True),
    sa.Column("file_upload_quota", sa.Integer(), nullable=True),
    sa.Column("image_upload_quota", sa.Integer(), nullable=True),
    sa.Column("gen_sections_quota", sa.Integer(), nullable=True),
    sa.Column("coach_mode_enabled", sa.Boolean(), nullable=True),
  )
  op.create_index(op.f("ix_user_tier_overrides_user_id"), "user_tier_overrides", ["user_id"], unique=False)

  op.create_table(
    "user_usage_metrics",
    sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True, nullable=False),
    sa.Column("subscription_tier_id", sa.Integer(), sa.ForeignKey("subscription_tiers.id"), nullable=False),
    sa.Column("files_uploaded_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("images_uploaded_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("sections_generated_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
  )

  op.create_table(
    "user_usage_logs",
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
    sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("action_type", sa.String(), nullable=False),
    sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
  )
  op.create_index(op.f("ix_user_usage_logs_user_id"), "user_usage_logs", ["user_id"], unique=False)

  # Seed subscription tiers.
  tiers = [
    {"name": "free", "max_file_upload_kb": 512, "highest_lesson_depth": "highlights", "max_sections_per_lesson": 2, "file_upload_quota": 0, "image_upload_quota": 0, "gen_sections_quota": 20, "coach_mode_enabled": False, "coach_voice_tier": "none"},
    {"name": "plus", "max_file_upload_kb": 1024, "highest_lesson_depth": "detailed", "max_sections_per_lesson": 6, "file_upload_quota": 5, "image_upload_quota": 5, "gen_sections_quota": 100, "coach_mode_enabled": True, "coach_voice_tier": "device"},
    {"name": "pro", "max_file_upload_kb": 2048, "highest_lesson_depth": "training", "max_sections_per_lesson": 10, "file_upload_quota": 10, "image_upload_quota": 10, "gen_sections_quota": 250, "coach_mode_enabled": True, "coach_voice_tier": "premium"},
  ]
  op.bulk_insert(sa.table("subscription_tiers", *[sa.column(key) for key in tiers[0].keys()]), tiers)

  # Backfill usage metrics for existing users defaulting to free tier.
  conn = op.get_bind()
  users = conn.execute(sa.text("select id from users")).fetchall()
  free_tier_id = conn.execute(sa.text("select id from subscription_tiers where name = 'free'")).scalar_one()
  for row in users:
    conn.execute(
      sa.text(
        "insert into user_usage_metrics (user_id, subscription_tier_id, files_uploaded_count, images_uploaded_count, sections_generated_count, last_updated) values (:user_id, :tier_id, 0, 0, 0, :now) on conflict (user_id) do nothing"
      ),
      {"user_id": row.id if hasattr(row, "id") else row[0], "tier_id": free_tier_id, "now": datetime.now(datetime.timezone.utc)},
    )


def downgrade() -> None:
  """Downgrade schema."""
  op.drop_table("user_usage_logs")
  op.drop_table("user_usage_metrics")
  op.drop_table("user_tier_overrides")
  op.drop_table("subscription_tiers")
