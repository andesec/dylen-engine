"""refactor lesson pipeline schema for planner-driven jobs

Revision ID: b7f6e4d3c2a1
Revises: 8a2554691669
Create Date: 2026-02-11 16:40:00.000000

"""
# destructive: approved

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import column_exists, table_exists
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b7f6e4d3c2a1"
down_revision: str | Sequence[str] | None = "8a2554691669"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Apply lesson pipeline schema updates."""
  if table_exists(table_name="lesson_requests") is False:
    op.create_table(
      "lesson_requests",
      sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
      sa.Column("creator_id", sa.String(), nullable=False),
      sa.Column("topic", sa.Text(), nullable=False),
      sa.Column("details", sa.Text(), nullable=True),
      sa.Column("outcomes_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
      sa.Column("blueprint", sa.String(), nullable=False),
      sa.Column("teaching_style_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
      sa.Column("learner_level", sa.String(), nullable=True),
      sa.Column("depth", sa.String(), nullable=False),
      sa.Column("lesson_language", sa.String(), nullable=False),
      sa.Column("secondary_language", sa.String(), nullable=True),
      sa.Column("widgets_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
      sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'queued'")),
      sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
      sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
      sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_lesson_requests_creator_id", "lesson_requests", ["creator_id"])

  if table_exists(table_name="lessons"):
    if not column_exists(table_name="lessons", column_name="lesson_request_id"):
      op.add_column("lessons", sa.Column("lesson_request_id", sa.Integer(), nullable=True))
      op.create_index("ix_lessons_lesson_request_id", "lessons", ["lesson_request_id"])
      op.create_foreign_key("fk_lessons_lesson_request_id", "lessons", "lesson_requests", ["lesson_request_id"], ["id"])

  if table_exists(table_name="sections") and not column_exists(table_name="sections", column_name="removed_widgets_csv"):
    op.add_column("sections", sa.Column("removed_widgets_csv", sa.Text(), nullable=True))

  if table_exists(table_name="subsections") is False:
    op.create_table(
      "subsections",
      sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
      sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.section_id", ondelete="CASCADE"), nullable=False),
      sa.Column("subsection_index", sa.Integer(), nullable=False),
      sa.Column("subsection_title", sa.Text(), nullable=False),
      sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
      sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
      sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
      sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
      sa.UniqueConstraint("section_id", "subsection_index", name="ux_subsections_section_subsection_index"),
    )
    op.create_index("ix_subsections_section_id", "subsections", ["section_id"])

  if table_exists(table_name="subsection_widgets") is False:
    op.create_table(
      "subsection_widgets",
      sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
      sa.Column("subsection_id", sa.Integer(), sa.ForeignKey("subsections.id", ondelete="CASCADE"), nullable=False),
      sa.Column("widget_id", sa.String(), nullable=True),
      sa.Column("widget_index", sa.Integer(), nullable=False),
      sa.Column("widget_type", sa.String(), nullable=False),
      sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
      sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
      sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
      sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
      sa.UniqueConstraint("subsection_id", "widget_index", "widget_type", name="ux_subsection_widgets_subsection_widget_index_type"),
    )
    op.create_index("ix_subsection_widgets_subsection_id", "subsection_widgets", ["subsection_id"])

  if table_exists(table_name="fenster_widgets"):
    op.rename_table("fenster_widgets", "fensters")
  if table_exists(table_name="fensters"):
    if not column_exists(table_name="fensters", column_name="creator_id"):
      op.add_column("fensters", sa.Column("creator_id", sa.String(), nullable=True))
      op.execute("UPDATE fensters SET creator_id = '' WHERE creator_id IS NULL")
      op.alter_column("fensters", "creator_id", nullable=False)
      op.create_index("ix_fensters_creator_id", "fensters", ["creator_id"])
    if not column_exists(table_name="fensters", column_name="status"):
      op.add_column("fensters", sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")))
    if not column_exists(table_name="fensters", column_name="is_archived"):
      op.add_column("fensters", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    if not column_exists(table_name="fensters", column_name="updated_at"):
      op.add_column("fensters", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

  if table_exists(table_name="subjective_input_widgets"):
    if table_exists(table_name="input_lines") is False:
      op.create_table(
        "input_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.String(), nullable=False),
        sa.Column("ai_prompt", sa.Text(), nullable=False),
        sa.Column("wordlist", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
      )
      op.create_index("ix_input_lines_creator_id", "input_lines", ["creator_id"])
    if table_exists(table_name="free_texts") is False:
      op.create_table(
        "free_texts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("creator_id", sa.String(), nullable=False),
        sa.Column("ai_prompt", sa.Text(), nullable=False),
        sa.Column("wordlist", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
      )
      op.create_index("ix_free_texts_creator_id", "free_texts", ["creator_id"])
    op.drop_table("subjective_input_widgets")

  if table_exists(table_name="tutor_audios"):
    if not column_exists(table_name="tutor_audios", column_name="creator_id"):
      op.add_column("tutor_audios", sa.Column("creator_id", sa.String(), nullable=True))
      op.execute("UPDATE tutor_audios SET creator_id = '' WHERE creator_id IS NULL")
      op.alter_column("tutor_audios", "creator_id", nullable=False)
      op.create_index("ix_tutor_audios_creator_id", "tutor_audios", ["creator_id"])
    if not column_exists(table_name="tutor_audios", column_name="status"):
      op.add_column("tutor_audios", sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")))
    if not column_exists(table_name="tutor_audios", column_name="is_archived"):
      op.add_column("tutor_audios", sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    if not column_exists(table_name="tutor_audios", column_name="updated_at"):
      op.add_column("tutor_audios", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

  if table_exists(table_name="illustrations"):
    if not column_exists(table_name="illustrations", column_name="creator_id"):
      op.add_column("illustrations", sa.Column("creator_id", sa.String(), nullable=True))
      op.execute("UPDATE illustrations SET creator_id = '' WHERE creator_id IS NULL")
      op.alter_column("illustrations", "creator_id", nullable=False)
      op.create_index("ix_illustrations_creator_id", "illustrations", ["creator_id"])


def downgrade() -> None:
  """Revert lesson pipeline schema updates."""
  if table_exists(table_name="illustrations") and column_exists(table_name="illustrations", column_name="creator_id"):
    op.drop_index("ix_illustrations_creator_id", table_name="illustrations")
    op.drop_column("illustrations", "creator_id")

  if table_exists(table_name="tutor_audios"):
    if column_exists(table_name="tutor_audios", column_name="updated_at"):
      op.drop_column("tutor_audios", "updated_at")
    if column_exists(table_name="tutor_audios", column_name="is_archived"):
      op.drop_column("tutor_audios", "is_archived")
    if column_exists(table_name="tutor_audios", column_name="status"):
      op.drop_column("tutor_audios", "status")
    if column_exists(table_name="tutor_audios", column_name="creator_id"):
      op.drop_index("ix_tutor_audios_creator_id", table_name="tutor_audios")
      op.drop_column("tutor_audios", "creator_id")

  if table_exists(table_name="input_lines"):
    op.drop_index("ix_input_lines_creator_id", table_name="input_lines")
    op.drop_table("input_lines")
  if table_exists(table_name="free_texts"):
    op.drop_index("ix_free_texts_creator_id", table_name="free_texts")
    op.drop_table("free_texts")
  if table_exists(table_name="subjective_input_widgets") is False:
    op.create_table(
      "subjective_input_widgets",
      sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
      sa.Column("section_id", sa.Integer(), sa.ForeignKey("sections.section_id", ondelete="CASCADE"), nullable=False),
      sa.Column("widget_type", sa.String(), nullable=False),
      sa.Column("ai_prompt", sa.Text(), nullable=False),
      sa.Column("wordlist", sa.Text(), nullable=True),
      sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

  if table_exists(table_name="fensters"):
    if column_exists(table_name="fensters", column_name="updated_at"):
      op.drop_column("fensters", "updated_at")
    if column_exists(table_name="fensters", column_name="is_archived"):
      op.drop_column("fensters", "is_archived")
    if column_exists(table_name="fensters", column_name="status"):
      op.drop_column("fensters", "status")
    if column_exists(table_name="fensters", column_name="creator_id"):
      op.drop_index("ix_fensters_creator_id", table_name="fensters")
      op.drop_column("fensters", "creator_id")
    op.rename_table("fensters", "fenster_widgets")

  if table_exists(table_name="subsection_widgets"):
    op.drop_index("ix_subsection_widgets_subsection_id", table_name="subsection_widgets")
    op.drop_table("subsection_widgets")
  if table_exists(table_name="subsections"):
    op.drop_index("ix_subsections_section_id", table_name="subsections")
    op.drop_table("subsections")

  if table_exists(table_name="sections") and column_exists(table_name="sections", column_name="removed_widgets_csv"):
    op.drop_column("sections", "removed_widgets_csv")

  if table_exists(table_name="lessons") and column_exists(table_name="lessons", column_name="lesson_request_id"):
    op.drop_constraint("fk_lessons_lesson_request_id", "lessons", type_="foreignkey")
    op.drop_index("ix_lessons_lesson_request_id", table_name="lessons")
    op.drop_column("lessons", "lesson_request_id")

  if table_exists(table_name="lesson_requests"):
    op.drop_index("ix_lesson_requests_creator_id", table_name="lesson_requests")
    op.drop_table("lesson_requests")
