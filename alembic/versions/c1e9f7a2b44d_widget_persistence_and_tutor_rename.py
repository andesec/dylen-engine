"""widget persistence expansion and tutor rename

Revision ID: c1e9f7a2b44d
Revises: b7f6e4d3c2a1
Create Date: 2026-02-11 21:10:00.000000
"""
# destructive: approved

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import column_exists, guarded_create_index, index_exists, table_exists
from sqlalchemy.dialects import postgresql

revision: str = "c1e9f7a2b44d"
down_revision: str | Sequence[str] | None = "b7f6e4d3c2a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_widget_table(name: str) -> None:
  if table_exists(table_name=name):
    return
  op.create_table(
    name,
    sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
    sa.Column("creator_id", sa.String(), nullable=False),
    sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
    sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
  )
  op.create_index(f"ix_{name}_creator_id", name, ["creator_id"])


def upgrade() -> None:
  if table_exists(table_name="tutor_audios") and table_exists(table_name="tutors") is False:
    op.rename_table("tutor_audios", "tutors")
  if table_exists(table_name="tutors"):
    # Table rename keeps legacy index names (ix_tutor_audios_*), but runtime schema verification
    # expects the new ix_tutors_* names.
    guarded_create_index("ix_tutors_id", "tutors", ["id"])
    guarded_create_index("ix_tutors_creator_id", "tutors", ["creator_id"])
    guarded_create_index("ix_tutors_job_id", "tutors", ["job_id"])

  for table_name in ["markdowns", "flipcards", "translations", "fill_blanks", "tables_data", "compares", "swipe_cards", "step_flows", "ascii_diagrams", "checklists", "interactive_terminals", "terminal_demos", "code_editors", "treeviews", "mcqs"]:
    _create_widget_table(table_name)

  if table_exists(table_name="sections"):
    if not column_exists(table_name="sections", column_name="illustration_id"):
      op.add_column("sections", sa.Column("illustration_id", sa.BigInteger(), nullable=True))
      op.create_index("ix_sections_illustration_id", "sections", ["illustration_id"])
      op.create_foreign_key("fk_sections_illustration_id", "sections", "illustrations", ["illustration_id"], ["id"], ondelete="SET NULL")
    if not column_exists(table_name="sections", column_name="markdown_id"):
      op.add_column("sections", sa.Column("markdown_id", sa.Integer(), nullable=True))
      op.create_index("ix_sections_markdown_id", "sections", ["markdown_id"])
      op.create_foreign_key("fk_sections_markdown_id", "sections", "markdowns", ["markdown_id"], ["id"], ondelete="SET NULL")
    if not column_exists(table_name="sections", column_name="tutor_id"):
      op.add_column("sections", sa.Column("tutor_id", sa.Integer(), nullable=True))
      op.create_index("ix_sections_tutor_id", "sections", ["tutor_id"])
      op.create_foreign_key("fk_sections_tutor_id", "sections", "tutors", ["tutor_id"], ["id"], ondelete="SET NULL")

  if table_exists(table_name="subsection_widgets"):
    if not column_exists(table_name="subsection_widgets", column_name="public_id"):
      op.add_column("subsection_widgets", sa.Column("public_id", sa.String(), nullable=True))
      op.execute("UPDATE subsection_widgets SET public_id = substring(md5(random()::text || clock_timestamp()::text), 1, 16) WHERE public_id IS NULL")
      op.alter_column("subsection_widgets", "public_id", nullable=False)
      op.create_index("ix_subsection_widgets_public_id", "subsection_widgets", ["public_id"], unique=True)
      op.create_unique_constraint("ux_subsection_widgets_public_id", "subsection_widgets", ["public_id"])

  if table_exists(table_name="tutor_audio_fragments") is False:
    op.create_table(
      "tutor_audio_fragments",
      sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
      sa.Column("tutor_audio_id", sa.Integer(), sa.ForeignKey("tutors.id", ondelete="CASCADE"), nullable=False),
      sa.Column("fragment_id", sa.Text(), nullable=False),
      sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.section_id", ondelete="SET NULL"), nullable=True),
      sa.Column("subsection_id", sa.Integer(), sa.ForeignKey("subsections.id", ondelete="SET NULL"), nullable=True),
      sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
      sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
      sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
      sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tutor_audio_fragments_tutor_audio_id", "tutor_audio_fragments", ["tutor_audio_id"])
    op.create_index("ix_tutor_audio_fragments_fragment_id", "tutor_audio_fragments", ["fragment_id"])
    op.create_index("ix_tutor_audio_fragments_section_id", "tutor_audio_fragments", ["section_id"])
    op.create_index("ix_tutor_audio_fragments_subsection_id", "tutor_audio_fragments", ["subsection_id"])

  if table_exists(table_name="section_illustrations"):
    op.execute(
      """
      UPDATE sections AS s
      SET illustration_id = si.illustration_id
      FROM section_illustrations AS si
      WHERE s.section_id = si.section_id
        AND s.illustration_id IS NULL
      """
    )
    op.drop_table("section_illustrations")


def downgrade() -> None:
  if table_exists(table_name="section_illustrations") is False:
    op.create_table(
      "section_illustrations",
      sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
      sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.section_id", ondelete="CASCADE"), nullable=False),
      sa.Column("illustration_id", sa.BigInteger(), sa.ForeignKey("illustrations.id", ondelete="CASCADE"), nullable=False),
      sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_section_illustrations_illustration_id", "section_illustrations", ["illustration_id"])
    op.create_index("ix_section_illustrations_section_id", "section_illustrations", ["section_id"])

  if table_exists(table_name="tutor_audio_fragments"):
    op.drop_index("ix_tutor_audio_fragments_subsection_id", table_name="tutor_audio_fragments")
    op.drop_index("ix_tutor_audio_fragments_section_id", table_name="tutor_audio_fragments")
    op.drop_index("ix_tutor_audio_fragments_fragment_id", table_name="tutor_audio_fragments")
    op.drop_index("ix_tutor_audio_fragments_tutor_audio_id", table_name="tutor_audio_fragments")
    op.drop_table("tutor_audio_fragments")

  if table_exists(table_name="subsection_widgets") and column_exists(table_name="subsection_widgets", column_name="public_id"):
    op.drop_constraint("ux_subsection_widgets_public_id", "subsection_widgets", type_="unique")
    op.drop_index("ix_subsection_widgets_public_id", table_name="subsection_widgets")
    op.drop_column("subsection_widgets", "public_id")

  if table_exists(table_name="sections"):
    if column_exists(table_name="sections", column_name="tutor_id"):
      op.drop_constraint("fk_sections_tutor_id", "sections", type_="foreignkey")
      op.drop_index("ix_sections_tutor_id", table_name="sections")
      op.drop_column("sections", "tutor_id")
    if column_exists(table_name="sections", column_name="markdown_id"):
      op.drop_constraint("fk_sections_markdown_id", "sections", type_="foreignkey")
      op.drop_index("ix_sections_markdown_id", table_name="sections")
      op.drop_column("sections", "markdown_id")
    if column_exists(table_name="sections", column_name="illustration_id"):
      op.drop_constraint("fk_sections_illustration_id", "sections", type_="foreignkey")
      op.drop_index("ix_sections_illustration_id", table_name="sections")
      op.drop_column("sections", "illustration_id")

  for table_name in ["mcqs", "treeviews", "code_editors", "terminal_demos", "interactive_terminals", "checklists", "ascii_diagrams", "step_flows", "swipe_cards", "compares", "tables_data", "fill_blanks", "translations", "flipcards", "markdowns"]:
    if table_exists(table_name=table_name):
      op.drop_index(f"ix_{table_name}_creator_id", table_name=table_name)
      op.drop_table(table_name)

  if table_exists(table_name="tutors"):
    if index_exists(index_name="ix_tutors_job_id"):
      op.drop_index("ix_tutors_job_id", table_name="tutors")
    if index_exists(index_name="ix_tutors_creator_id"):
      op.drop_index("ix_tutors_creator_id", table_name="tutors")
    if index_exists(index_name="ix_tutors_id"):
      op.drop_index("ix_tutors_id", table_name="tutors")

  if table_exists(table_name="tutors") and table_exists(table_name="tutor_audios") is False:
    op.rename_table("tutors", "tutor_audios")
