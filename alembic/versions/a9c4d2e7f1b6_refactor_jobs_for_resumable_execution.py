"""refactor jobs table and add resumable checkpoint/event tables

Revision ID: a9c4d2e7f1b6
Revises: 3c0d47535e71
Create Date: 2026-02-12 13:30:00.000000
"""
# destructive: approved

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_create_index, guarded_create_table, guarded_create_unique_constraint, guarded_drop_table, table_exists
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a9c4d2e7f1b6"
down_revision: str | Sequence[str] | None = "3c0d47535e71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Apply resumable jobs schema."""
  if table_exists(table_name="jobs"):
    guarded_drop_table("jobs")
  guarded_create_table(
    "jobs",
    sa.Column("job_id", sa.String(), nullable=False),
    sa.Column("root_job_id", sa.String(), nullable=False),
    sa.Column("resume_source_job_id", sa.String(), nullable=True),
    sa.Column("superseded_by_job_id", sa.String(), nullable=True),
    sa.Column("user_id", sa.String(), nullable=True),
    sa.Column("job_kind", sa.String(), nullable=False),
    sa.Column("request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("parent_job_id", sa.String(), nullable=True),
    sa.Column("lesson_id", sa.String(), nullable=True),
    sa.Column("section_id", sa.Integer(), nullable=True),
    sa.Column("target_agent", sa.String(), nullable=True),
    sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("error_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("created_at", sa.String(), nullable=False, server_default=sa.text("to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')")),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("updated_at", sa.String(), nullable=False, server_default=sa.text("to_char((now() AT TIME ZONE 'UTC'), 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')")),
    sa.Column("completed_at", sa.String(), nullable=True),
    sa.Column("idempotency_key", sa.String(), nullable=False),
    sa.PrimaryKeyConstraint("job_id"),
    sa.UniqueConstraint("user_id", "job_kind", "idempotency_key", name="ux_jobs_user_kind_idempotency"),
  )
  guarded_create_index("ix_jobs_root_job_id", "jobs", ["root_job_id"], unique=False)
  guarded_create_index("ix_jobs_resume_source_job_id", "jobs", ["resume_source_job_id"], unique=False)
  guarded_create_index("ix_jobs_superseded_by_job_id", "jobs", ["superseded_by_job_id"], unique=False)
  guarded_create_index("ix_jobs_user_id", "jobs", ["user_id"], unique=False)
  guarded_create_index("ix_jobs_job_kind", "jobs", ["job_kind"], unique=False)
  guarded_create_index("ix_jobs_parent_job_id", "jobs", ["parent_job_id"], unique=False)
  guarded_create_index("ix_jobs_lesson_id", "jobs", ["lesson_id"], unique=False)
  guarded_create_index("ix_jobs_section_id", "jobs", ["section_id"], unique=False)
  guarded_create_index("ix_jobs_idempotency_key", "jobs", ["idempotency_key"], unique=False)
  guarded_create_index("ux_jobs_active_resume_source", "jobs", ["resume_source_job_id"], unique=True, postgresql_where=sa.text("resume_source_job_id IS NOT NULL AND status IN ('queued', 'running')"))

  guarded_create_table(
    "job_checkpoints",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
    sa.Column("stage", sa.String(), nullable=False),
    sa.Column("section_index", sa.Integer(), nullable=True),
    sa.Column("state", sa.String(), nullable=False),
    sa.Column("artifact_refs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    sa.Column("last_error", sa.Text(), nullable=True),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.PrimaryKeyConstraint("id"),
  )
  guarded_create_index("ix_job_checkpoints_job_id", "job_checkpoints", ["job_id"], unique=False)
  guarded_create_index("ix_job_checkpoints_state", "job_checkpoints", ["state"], unique=False)
  guarded_create_index("ux_job_checkpoints_job_stage_section_not_null", "job_checkpoints", ["job_id", "stage", "section_index"], unique=True, postgresql_where=sa.text("section_index IS NOT NULL"))
  guarded_create_index("ux_job_checkpoints_job_stage_null", "job_checkpoints", ["job_id", "stage"], unique=True, postgresql_where=sa.text("section_index IS NULL"))

  guarded_create_table(
    "job_events",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
    sa.Column("event_type", sa.String(), nullable=False),
    sa.Column("message", sa.Text(), nullable=False),
    sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.PrimaryKeyConstraint("id"),
  )
  guarded_create_index("ix_job_events_job_id", "job_events", ["job_id"], unique=False)
  guarded_create_index("ix_job_events_event_type", "job_events", ["event_type"], unique=False)

  # Repair legacy duplicate section ordering by moving duplicate rows to unique tail indexes per lesson.
  op.execute(
    sa.text(
      """
      WITH duplicate_rows AS (
        SELECT
          section_id,
          lesson_id,
          order_index,
          ROW_NUMBER() OVER (PARTITION BY lesson_id, order_index ORDER BY section_id) AS dup_rank
        FROM sections
      ),
      base AS (
        SELECT lesson_id, COALESCE(MAX(order_index), 0) AS max_order
        FROM sections
        GROUP BY lesson_id
      ),
      reassigned AS (
        SELECT
          d.section_id,
          b.max_order + ROW_NUMBER() OVER (PARTITION BY d.lesson_id ORDER BY d.order_index, d.section_id) AS new_order_index
        FROM duplicate_rows d
        JOIN base b ON b.lesson_id = d.lesson_id
        WHERE d.dup_rank > 1
      )
      UPDATE sections AS s
      SET order_index = reassigned.new_order_index
      FROM reassigned
      WHERE s.section_id = reassigned.section_id
      """
    )
  )
  guarded_create_unique_constraint("ux_sections_lesson_order_index", "sections", ["lesson_id", "order_index"])


def downgrade() -> None:
  """No downgrade path; schema is intentionally reset-oriented."""
  pass
