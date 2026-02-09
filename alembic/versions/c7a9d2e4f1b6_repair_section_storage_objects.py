"""Repair section storage objects after branch/stamp drift.

Revision ID: c7a9d2e4f1b6
Revises: 9b1f2d4c7e31
Create Date: 2026-02-08 00:00:04.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_add_column, guarded_create_index, guarded_create_table
from sqlalchemy.dialects import postgresql

revision = "c7a9d2e4f1b6"
down_revision = "9b1f2d4c7e31"
branch_labels = None
depends_on = None
REPAIR_SAFE = True
REPAIR_TARGETS = {
  "tables": ["section_errors"],
  "columns": [
    "sections.content_shorthand",
    "section_errors.id",
    "section_errors.section_id",
    "section_errors.error_index",
    "section_errors.error_message",
    "section_errors.error_path",
    "section_errors.section_scope",
    "section_errors.subsection_index",
    "section_errors.item_index",
  ],
  "indexes": ["ix_section_errors_section_id"],
}


def _assert_sections_pk_integer() -> None:
  """Fail fast when sections.section_id has an unexpected type."""
  statement = sa.text(
    """
    SELECT data_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'sections'
      AND column_name = 'section_id'
    """
  )
  result = op.get_bind().execute(statement).scalar_one_or_none()
  if result is None:
    raise RuntimeError("sections.section_id is missing; cannot repair section storage objects.")
  if str(result).lower() != "integer":
    raise RuntimeError(f"sections.section_id must be integer before repairing section storage objects (got {result}).")


def upgrade() -> None:
  """Upgrade schema."""
  _assert_sections_pk_integer()
  guarded_add_column("sections", sa.Column("content_shorthand", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
  guarded_create_table(
    "section_errors",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("section_id", sa.Integer(), nullable=False),
    sa.Column("error_index", sa.Integer(), nullable=False),
    sa.Column("error_message", sa.Text(), nullable=False),
    sa.Column("error_path", sa.Text(), nullable=True),
    sa.Column("section_scope", sa.String(), nullable=True),
    sa.Column("subsection_index", sa.Integer(), nullable=True),
    sa.Column("item_index", sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(["section_id"], ["sections.section_id"], ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id"),
  )
  guarded_add_column("section_errors", sa.Column("error_path", sa.Text(), nullable=True))
  guarded_add_column("section_errors", sa.Column("section_scope", sa.String(), nullable=True))
  guarded_add_column("section_errors", sa.Column("subsection_index", sa.Integer(), nullable=True))
  guarded_add_column("section_errors", sa.Column("item_index", sa.Integer(), nullable=True))
  guarded_create_index(op.f("ix_section_errors_section_id"), "section_errors", ["section_id"], unique=False)
  op.execute(sa.text("UPDATE sections SET content_shorthand = content WHERE content_shorthand IS NULL"))


def downgrade() -> None:
  """Downgrade schema."""
  # Repair migration is intentionally non-destructive.
  return None
