"""Add sections table.

Revision ID: b94c8e7d2f1a
Revises: 0d8b6c2b9a2a
Create Date: 2026-02-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_create_index, guarded_create_table, guarded_drop_index, guarded_drop_table
from sqlalchemy.dialects import postgresql

revision = "b94c8e7d2f1a"
down_revision = "0d8b6c2b9a2a"
branch_labels = None
depends_on = None
REPAIR_SAFE = True
REPAIR_TARGETS = {"tables": ["sections"], "columns": ["sections.section_id", "sections.lesson_id", "sections.title", "sections.order_index", "sections.status", "sections.content"], "indexes": ["ix_sections_lesson_id"]}


def upgrade() -> None:
  """Upgrade schema."""
  guarded_create_table(
    "sections",
    sa.Column("section_id", sa.String(), nullable=False),
    sa.Column("lesson_id", sa.String(), nullable=False),
    sa.Column("title", sa.String(), nullable=False),
    sa.Column("order_index", sa.Integer(), nullable=False),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(["lesson_id"], ["lessons.lesson_id"]),
    sa.PrimaryKeyConstraint("section_id"),
  )
  guarded_create_index(op.f("ix_sections_lesson_id"), "sections", ["lesson_id"], unique=False)


def downgrade() -> None:
  """Downgrade schema."""
  guarded_drop_index(op.f("ix_sections_lesson_id"), table_name="sections")
  guarded_drop_table("sections")
