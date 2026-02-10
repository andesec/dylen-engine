"""Add jobs hierarchy and job kind fields.

Revision ID: 3055a1cfd37e
Revises: 7c3d9e2a1f44
Create Date: 2026-02-09 23:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_add_column, guarded_create_index, guarded_create_unique_constraint

revision = "3055a1cfd37e"
down_revision = "7c3d9e2a1f44"
branch_labels = None
depends_on = None

REPAIR_TARGETS = {
  "columns": ["jobs.job_kind", "jobs.parent_job_id", "jobs.lesson_id", "jobs.section_id"],
  "indexes": ["ix_jobs_job_kind", "ix_jobs_parent_job_id", "ix_jobs_lesson_id", "ix_jobs_section_id", "ux_jobs_user_kind_idempotency"],
  "constraints": ["ux_jobs_user_kind_idempotency"],
}


def upgrade() -> None:
  """Upgrade schema."""
  guarded_add_column("jobs", sa.Column("job_kind", sa.String(), nullable=True))
  guarded_add_column("jobs", sa.Column("parent_job_id", sa.String(), nullable=True))
  guarded_add_column("jobs", sa.Column("lesson_id", sa.String(), nullable=True))
  guarded_add_column("jobs", sa.Column("section_id", sa.Integer(), nullable=True))
  # Backfill safe defaults so non-null constraints can be enforced.
  op.execute("UPDATE jobs SET job_kind = COALESCE(job_kind, 'lesson')")
  op.execute("UPDATE jobs SET idempotency_key = COALESCE(NULLIF(idempotency_key, ''), job_id)")
  # Enforce strict non-null semantics for new job creation flows.
  op.execute("ALTER TABLE jobs ALTER COLUMN job_kind SET NOT NULL")
  op.execute("ALTER TABLE jobs ALTER COLUMN idempotency_key SET NOT NULL")
  guarded_create_index("ix_jobs_job_kind", "jobs", ["job_kind"], unique=False)
  guarded_create_index("ix_jobs_parent_job_id", "jobs", ["parent_job_id"], unique=False)
  guarded_create_index("ix_jobs_lesson_id", "jobs", ["lesson_id"], unique=False)
  guarded_create_index("ix_jobs_section_id", "jobs", ["section_id"], unique=False)
  guarded_create_unique_constraint("ux_jobs_user_kind_idempotency", "jobs", ["user_id", "job_kind", "idempotency_key"])


def downgrade() -> None:
  """Downgrade schema."""
  # Keep downgrade non-destructive for production safety.
  return None
