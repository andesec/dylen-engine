"""add concurrency limits

Revision ID: 9c9c9c9c9c9c
Revises: 3a2bfc86881f
Create Date: 2024-05-22 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "9c9c9c9c9c9c"
down_revision = '3b3bfc86881f'
branch_labels = None
depends_on = None


def upgrade():
  # subscription_tiers
  op.add_column("subscription_tiers", sa.Column("concurrent_lesson_limit", sa.Integer(), nullable=True, server_default="1"))
  op.add_column("subscription_tiers", sa.Column("concurrent_research_limit", sa.Integer(), nullable=True, server_default="1"))
  op.add_column("subscription_tiers", sa.Column("concurrent_writing_limit", sa.Integer(), nullable=True, server_default="1"))
  op.add_column("subscription_tiers", sa.Column("concurrent_coach_limit", sa.Integer(), nullable=True, server_default="1"))

  # user_tier_overrides
  op.add_column("user_tier_overrides", sa.Column("concurrent_lesson_limit", sa.Integer(), nullable=True))
  op.add_column("user_tier_overrides", sa.Column("concurrent_research_limit", sa.Integer(), nullable=True))
  op.add_column("user_tier_overrides", sa.Column("concurrent_writing_limit", sa.Integer(), nullable=True))
  op.add_column("user_tier_overrides", sa.Column("concurrent_coach_limit", sa.Integer(), nullable=True))


def downgrade():
  op.drop_column("user_tier_overrides", "concurrent_coach_limit")
  op.drop_column("user_tier_overrides", "concurrent_writing_limit")
  op.drop_column("user_tier_overrides", "concurrent_research_limit")
  op.drop_column("user_tier_overrides", "concurrent_lesson_limit")

  op.drop_column("subscription_tiers", "concurrent_coach_limit")
  op.drop_column("subscription_tiers", "concurrent_writing_limit")
  op.drop_column("subscription_tiers", "concurrent_research_limit")
  op.drop_column("subscription_tiers", "concurrent_lesson_limit")
