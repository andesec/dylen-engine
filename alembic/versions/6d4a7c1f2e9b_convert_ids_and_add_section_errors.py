"""Convert section and audit ids to integers and add section_errors.

Revision ID: 6d4a7c1f2e9b
Revises: 8c17f9a4e2d1
Create Date: 2026-02-08 00:00:02.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_create_index, guarded_create_table, guarded_drop_index, guarded_drop_table

revision = "6d4a7c1f2e9b"
down_revision = "8c17f9a4e2d1"
branch_labels = None
depends_on = None
REPAIR_SAFE = False
REPAIR_TARGETS = {
  "tables": ["section_errors"],
  "columns": ["sections.section_id", "llm_call_audit.id", "section_errors.id", "section_errors.section_id", "section_errors.error_index", "section_errors.error_message"],
  "indexes": ["ix_section_errors_section_id"],
}


def _convert_sections_pk_to_integer() -> None:
  """Replace sections.section_id string primary key with integer autoincrement primary key."""
  op.add_column("sections", sa.Column("section_id_int", sa.Integer(), nullable=True))
  op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS sections_section_id_seq"))
  op.execute(sa.text("ALTER TABLE sections ALTER COLUMN section_id_int SET DEFAULT nextval('sections_section_id_seq')"))
  op.execute(sa.text("UPDATE sections SET section_id_int = nextval('sections_section_id_seq') WHERE section_id_int IS NULL"))
  op.execute(sa.text("SELECT setval('sections_section_id_seq', COALESCE((SELECT MAX(section_id_int) FROM sections), 0), true)"))
  op.alter_column("sections", "section_id_int", nullable=False)
  op.drop_constraint("sections_pkey", "sections", type_="primary")
  op.drop_column("sections", "section_id")
  op.alter_column("sections", "section_id_int", new_column_name="section_id")
  op.create_primary_key("sections_pkey", "sections", ["section_id"])
  op.execute(sa.text("ALTER SEQUENCE sections_section_id_seq OWNED BY sections.section_id"))


def _convert_llm_call_audit_pk_to_integer() -> None:
  """Replace llm_call_audit.id string primary key with integer autoincrement primary key."""
  op.add_column("llm_call_audit", sa.Column("id_int", sa.Integer(), nullable=True))
  op.execute(sa.text("CREATE SEQUENCE IF NOT EXISTS llm_call_audit_id_seq"))
  op.execute(sa.text("ALTER TABLE llm_call_audit ALTER COLUMN id_int SET DEFAULT nextval('llm_call_audit_id_seq')"))
  op.execute(sa.text("UPDATE llm_call_audit SET id_int = nextval('llm_call_audit_id_seq') WHERE id_int IS NULL"))
  op.execute(sa.text("SELECT setval('llm_call_audit_id_seq', COALESCE((SELECT MAX(id_int) FROM llm_call_audit), 0), true)"))
  op.alter_column("llm_call_audit", "id_int", nullable=False)
  op.drop_constraint("llm_call_audit_pkey", "llm_call_audit", type_="primary")
  op.drop_column("llm_call_audit", "id")
  op.alter_column("llm_call_audit", "id_int", new_column_name="id")
  op.create_primary_key("llm_call_audit_pkey", "llm_call_audit", ["id"])
  op.execute(sa.text("ALTER SEQUENCE llm_call_audit_id_seq OWNED BY llm_call_audit.id"))


def upgrade() -> None:
  """Upgrade schema."""
  _convert_sections_pk_to_integer()
  _convert_llm_call_audit_pk_to_integer()
  guarded_create_table(
    "section_errors",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("section_id", sa.Integer(), nullable=False),
    sa.Column("error_index", sa.Integer(), nullable=False),
    sa.Column("error_message", sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(["section_id"], ["sections.section_id"], ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id"),
  )
  guarded_create_index(op.f("ix_section_errors_section_id"), "section_errors", ["section_id"], unique=False)


def _convert_sections_pk_to_string() -> None:
  """Replace sections.section_id integer primary key with string primary key."""
  op.add_column("sections", sa.Column("section_id_text", sa.String(), nullable=True))
  op.execute(sa.text("UPDATE sections SET section_id_text = section_id::text WHERE section_id_text IS NULL"))
  op.alter_column("sections", "section_id_text", nullable=False)
  op.drop_constraint("sections_pkey", "sections", type_="primary")
  op.drop_column("sections", "section_id")
  op.alter_column("sections", "section_id_text", new_column_name="section_id")
  op.create_primary_key("sections_pkey", "sections", ["section_id"])
  op.execute(sa.text("DROP SEQUENCE IF EXISTS sections_section_id_seq"))


def _convert_llm_call_audit_pk_to_string() -> None:
  """Replace llm_call_audit.id integer primary key with string primary key."""
  op.add_column("llm_call_audit", sa.Column("id_text", sa.String(), nullable=True))
  op.execute(sa.text("UPDATE llm_call_audit SET id_text = id::text WHERE id_text IS NULL"))
  op.alter_column("llm_call_audit", "id_text", nullable=False)
  op.drop_constraint("llm_call_audit_pkey", "llm_call_audit", type_="primary")
  op.drop_column("llm_call_audit", "id")
  op.alter_column("llm_call_audit", "id_text", new_column_name="id")
  op.create_primary_key("llm_call_audit_pkey", "llm_call_audit", ["id"])
  op.execute(sa.text("DROP SEQUENCE IF EXISTS llm_call_audit_id_seq"))


def downgrade() -> None:
  """Downgrade schema."""
  guarded_drop_index(op.f("ix_section_errors_section_id"), table_name="section_errors")
  guarded_drop_table("section_errors")
  _convert_llm_call_audit_pk_to_string()
  _convert_sections_pk_to_string()
