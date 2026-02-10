"""Add subjective_input_widgets table.

Revision ID: 5fca8c2e0924
Revises: e8f4a4b9d2c1
Create Date: 2026-02-10 12:05:01.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_create_index, guarded_create_table, guarded_drop_index, guarded_drop_table

# revision identifiers, used by Alembic.
revision = "5fca8c2e0924"
down_revision = "e8f4a4b9d2c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
  guarded_create_table(
    "subjective_input_widgets",
    sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
    sa.Column("section_id", sa.Integer(), nullable=False),
    sa.Column("widget_type", sa.String(), nullable=False),
    sa.Column("ai_prompt", sa.Text(), nullable=False),
    sa.Column("wordlist", sa.Text(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(["section_id"], ["sections.section_id"], ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id"),
  )
  guarded_create_index(op.f("ix_subjective_input_widgets_section_id"), "subjective_input_widgets", ["section_id"], unique=False)


def downgrade() -> None:
  guarded_drop_index(op.f("ix_subjective_input_widgets_section_id"), table_name="subjective_input_widgets")
  guarded_drop_table("subjective_input_widgets")
