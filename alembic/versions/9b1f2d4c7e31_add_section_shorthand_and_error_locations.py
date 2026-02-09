"""Add shorthand content column and section error location metadata.

Revision ID: 9b1f2d4c7e31
Revises: 6d4a7c1f2e9b
Create Date: 2026-02-08 00:00:03.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_add_column, guarded_drop_column
from sqlalchemy.dialects import postgresql

revision = "9b1f2d4c7e31"
down_revision = "6d4a7c1f2e9b"
branch_labels = None
depends_on = None
REPAIR_SAFE = True
REPAIR_TARGETS = {"columns": ["sections.content_shorthand", "section_errors.error_path", "section_errors.section_scope", "section_errors.subsection_index", "section_errors.item_index"]}


def upgrade() -> None:
  """Upgrade schema."""
  guarded_add_column("sections", sa.Column("content_shorthand", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
  guarded_add_column("section_errors", sa.Column("error_path", sa.Text(), nullable=True))
  guarded_add_column("section_errors", sa.Column("section_scope", sa.String(), nullable=True))
  guarded_add_column("section_errors", sa.Column("subsection_index", sa.Integer(), nullable=True))
  guarded_add_column("section_errors", sa.Column("item_index", sa.Integer(), nullable=True))
  # Preserve backward compatibility for existing rows that stored shorthand in content.
  op.execute(sa.text("UPDATE sections SET content_shorthand = content WHERE content_shorthand IS NULL"))


def downgrade() -> None:
  """Downgrade schema."""
  guarded_drop_column("section_errors", "item_index")
  guarded_drop_column("section_errors", "subsection_index")
  guarded_drop_column("section_errors", "section_scope")
  guarded_drop_column("section_errors", "error_path")
  guarded_drop_column("sections", "content_shorthand")
