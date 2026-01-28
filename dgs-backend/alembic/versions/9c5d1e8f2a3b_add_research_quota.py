"""add_research_quota

Revision ID: 9c5d1e8f2a3b
Revises: 50f5e7581de6
Create Date: 2024-05-22 10:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "9c5d1e8f2a3b"
down_revision = "50f5e7581de6"
branch_labels = None
depends_on = None


def upgrade():
  # Add research_quota to subscription_tiers
  op.add_column("subscription_tiers", sa.Column("research_quota", sa.Integer(), nullable=True))

  # Add research_quota to user_tier_overrides
  op.add_column("user_tier_overrides", sa.Column("research_quota", sa.Integer(), nullable=True))

  # Add research_usage_count to user_usage_metrics
  op.add_column("user_usage_metrics", sa.Column("research_usage_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
  # Remove columns
  op.drop_column("user_usage_metrics", "research_usage_count")
  op.drop_column("user_tier_overrides", "research_quota")
  op.drop_column("subscription_tiers", "research_quota")
