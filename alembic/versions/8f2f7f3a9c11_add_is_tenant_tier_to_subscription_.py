"""add_is_tenant_tier_to_subscription_tiers

Revision ID: 8f2f7f3a9c11
Revises: 0b7d3f4f725b
Create Date: 2026-02-10 21:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import column_exists, table_exists

# revision identifiers, used by Alembic.
revision: str = "8f2f7f3a9c11"
down_revision: str | Sequence[str] | None = "0b7d3f4f725b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  # Add tenant-tier marker so strict feature-gating can branch tenant vs non-tenant chains.
  if not table_exists(table_name="subscription_tiers"):
    return
  if column_exists(table_name="subscription_tiers", column_name="is_tenant_tier"):
    # Keep bootstrap behavior conservative: no tiers are tenant tiers until explicitly configured.
    op.execute("UPDATE subscription_tiers SET is_tenant_tier = false")
    return
  op.add_column("subscription_tiers", sa.Column("is_tenant_tier", sa.Boolean(), nullable=False, server_default=sa.text("false")))
  # Keep bootstrap behavior conservative for existing rows.
  op.execute("UPDATE subscription_tiers SET is_tenant_tier = false")


def downgrade() -> None:
  """Downgrade schema."""
  # Remove tenant-tier marker only when present to keep downgrades idempotent.
  if not table_exists(table_name="subscription_tiers"):
    return
  if not column_exists(table_name="subscription_tiers", column_name="is_tenant_tier"):
    return
  op.drop_column("subscription_tiers", "is_tenant_tier")
