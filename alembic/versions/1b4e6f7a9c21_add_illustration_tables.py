"""Add illustration assets and section illustration junction table.

Revision ID: 1b4e6f7a9c21
Revises: c7a9d2e4f1b6
Create Date: 2026-02-09 20:05:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from app.core.migration_guards import guarded_create_index, guarded_create_table
from sqlalchemy.dialects import postgresql

revision = "1b4e6f7a9c21"
down_revision = "c7a9d2e4f1b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
  """Upgrade schema."""
  guarded_create_table(
    "illustrations",
    sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column("storage_bucket", sa.Text(), nullable=False),
    sa.Column("storage_object_name", sa.Text(), nullable=False),
    sa.Column("mime_type", sa.String(), nullable=False),
    sa.Column("caption", sa.Text(), nullable=False),
    sa.Column("ai_prompt", sa.Text(), nullable=False),
    sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("regenerate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.PrimaryKeyConstraint("id"),
  )
  guarded_create_index("ix_illustrations_storage_object_name", "illustrations", ["storage_object_name"], unique=False)
  guarded_create_index("ux_illustrations_bucket_object", "illustrations", ["storage_bucket", "storage_object_name"], unique=True)

  guarded_create_table(
    "section_illustrations",
    sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column("section_id", sa.Integer(), nullable=False),
    sa.Column("illustration_id", sa.BigInteger(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    sa.ForeignKeyConstraint(["illustration_id"], ["illustrations.id"], ondelete="CASCADE"),
    sa.ForeignKeyConstraint(["section_id"], ["sections.section_id"], ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id"),
  )
  guarded_create_index("ix_section_illustrations_section_id", "section_illustrations", ["section_id"], unique=False)
  guarded_create_index("ix_section_illustrations_illustration_id", "section_illustrations", ["illustration_id"], unique=False)


def downgrade() -> None:
  """Downgrade schema."""
  # Keep downgrade non-destructive for production safety.
  return None
