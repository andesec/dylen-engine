"""add llm model pricing table

Revision ID: f7b2c1d4e6a9
Revises: 271313020e9b
Create Date: 2026-02-13 10:00:00.000000
"""
# backfill: ok

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_create_index, guarded_create_table, guarded_drop_table, table_exists

revision: str = "f7b2c1d4e6a9"
down_revision: str | Sequence[str] | None = "271313020e9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  # Create a global pricing table for model cost configuration.
  guarded_create_table(
    "llm_model_pricing",
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("provider", sa.String(), nullable=False),
    sa.Column("model", sa.String(), nullable=False),
    sa.Column("input_per_1m", sa.Numeric(12, 6), nullable=False),
    sa.Column("output_per_1m", sa.Numeric(12, 6), nullable=False),
    sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.UniqueConstraint("provider", "model", name="ux_llm_model_pricing_provider_model"),
  )
  guarded_create_index("ix_llm_model_pricing_provider", "llm_model_pricing", ["provider"], unique=False)
  guarded_create_index("ix_llm_model_pricing_model", "llm_model_pricing", ["model"], unique=False)

  if table_exists(table_name="runtime_config_values"):
    # Remove deprecated runtime config pricing keys after table migration.
    op.execute(sa.text("DELETE FROM runtime_config_values WHERE key = 'llm.pricing.gemini_models'"))


def downgrade() -> None:
  # Drop pricing table if migration is rolled back.
  guarded_drop_table("llm_model_pricing")
