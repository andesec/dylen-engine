"""Adopt existing tables to SQLAlchemy with idempotent safeguards.

Revision ID: 989029857d49
Revises: 241feda2db69
Create Date: 2026-01-19 23:05:42.326213

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "989029857d49"
down_revision: str | Sequence[str] | None = "241feda2db69"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_exists(inspector, table_name: str, index_name: str, existing_tables: set[str]) -> bool:
  """Detect index existence to avoid duplicate/invalid drops."""
  # Skip index inspection when the table does not exist.
  if table_name not in existing_tables:
    return False
  return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
  """Upgrade schema with guards for legacy installations."""
  # Inspect schema so operations only run when tables exist.
  inspector = inspect(op.get_bind())
  existing_tables = set(inspector.get_table_names())

  # Remove legacy meta tables when they exist.
  if "dgs_storage_meta" in existing_tables:
    op.drop_table("dgs_storage_meta")

  if "llm_audit_meta" in existing_tables:
    op.drop_table("llm_audit_meta")

  # Normalize dgs_jobs schema when the table exists.
  if "dgs_jobs" in existing_tables:
    op.alter_column("dgs_jobs", "job_id", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_jobs", "status", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_jobs", "phase", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_jobs", "subphase", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    op.alter_column("dgs_jobs", "current_section_status", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    op.alter_column("dgs_jobs", "current_section_title", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    op.alter_column("dgs_jobs", "retry_parent_job_id", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    op.alter_column("dgs_jobs", "created_at", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_jobs", "updated_at", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_jobs", "completed_at", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    op.alter_column("dgs_jobs", "idempotency_key", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    if _index_exists(inspector, "dgs_jobs", op.f("dgs_jobs_idempotency_idx"), existing_tables):
      op.drop_index(op.f("dgs_jobs_idempotency_idx"), table_name="dgs_jobs")
    if _index_exists(inspector, "dgs_jobs", op.f("dgs_jobs_status_created_idx"), existing_tables):
      op.drop_index(op.f("dgs_jobs_status_created_idx"), table_name="dgs_jobs")
    if not _index_exists(inspector, "dgs_jobs", op.f("ix_dgs_jobs_idempotency_key"), existing_tables):
      op.create_index(op.f("ix_dgs_jobs_idempotency_key"), "dgs_jobs", ["idempotency_key"], unique=False)

  # Normalize dgs_lessons schema when the table exists.
  if "dgs_lessons" in existing_tables:
    op.alter_column("dgs_lessons", "lesson_id", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "topic", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "title", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "created_at", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "schema_version", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "prompt_version", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "provider_a", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "model_a", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "provider_b", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "model_b", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "status", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("dgs_lessons", "idempotency_key", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    if _index_exists(inspector, "dgs_lessons", op.f("dgs_lessons_idempotency_idx"), existing_tables):
      op.drop_index(op.f("dgs_lessons_idempotency_idx"), table_name="dgs_lessons")
    if not _index_exists(inspector, "dgs_lessons", op.f("ix_dgs_lessons_idempotency_key"), existing_tables):
      op.create_index(op.f("ix_dgs_lessons_idempotency_key"), "dgs_lessons", ["idempotency_key"], unique=False)

  # Normalize llm_call_audit schema when the table exists.
  if "llm_call_audit" in existing_tables:
    op.alter_column("llm_call_audit", "id", existing_type=sa.UUID(), type_=sa.String(), existing_nullable=False)
    op.alter_column("llm_call_audit", "created_at", existing_type=postgresql.TIMESTAMP(timezone=True), nullable=True, existing_server_default=sa.text("now()"))
    op.alter_column("llm_call_audit", "agent", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("llm_call_audit", "provider", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("llm_call_audit", "model", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("llm_call_audit", "lesson_topic", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    op.alter_column("llm_call_audit", "request_type", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    op.alter_column("llm_call_audit", "purpose", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    op.alter_column("llm_call_audit", "call_index", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    op.alter_column("llm_call_audit", "job_id", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=True)
    op.alter_column("llm_call_audit", "status", existing_type=sa.TEXT(), type_=sa.String(), existing_nullable=False)
    if _index_exists(inspector, "llm_call_audit", op.f("llm_call_audit_agent_idx"), existing_tables):
      op.drop_index(op.f("llm_call_audit_agent_idx"), table_name="llm_call_audit")
    if _index_exists(inspector, "llm_call_audit", op.f("llm_call_audit_created_at_idx"), existing_tables):
      op.drop_index(op.f("llm_call_audit_created_at_idx"), table_name="llm_call_audit")
    if _index_exists(inspector, "llm_call_audit", op.f("llm_call_audit_model_idx"), existing_tables):
      op.drop_index(op.f("llm_call_audit_model_idx"), table_name="llm_call_audit")
    if _index_exists(inspector, "llm_call_audit", op.f("llm_call_audit_topic_idx"), existing_tables):
      op.drop_index(op.f("llm_call_audit_topic_idx"), table_name="llm_call_audit")


def downgrade() -> None:
  """Downgrade schema with guards for missing tables."""
  # Inspect schema so operations only run when tables exist.
  inspector = inspect(op.get_bind())
  existing_tables = set(inspector.get_table_names())

  # Restore llm_call_audit indexes and types when available.
  if "llm_call_audit" in existing_tables:
    if not _index_exists(inspector, "llm_call_audit", op.f("llm_call_audit_topic_idx"), existing_tables):
      op.create_index(op.f("llm_call_audit_topic_idx"), "llm_call_audit", ["lesson_topic"], unique=False)
    if not _index_exists(inspector, "llm_call_audit", op.f("llm_call_audit_model_idx"), existing_tables):
      op.create_index(op.f("llm_call_audit_model_idx"), "llm_call_audit", ["model"], unique=False)
    if not _index_exists(inspector, "llm_call_audit", op.f("llm_call_audit_created_at_idx"), existing_tables):
      op.create_index(op.f("llm_call_audit_created_at_idx"), "llm_call_audit", ["created_at"], unique=False)
    if not _index_exists(inspector, "llm_call_audit", op.f("llm_call_audit_agent_idx"), existing_tables):
      op.create_index(op.f("llm_call_audit_agent_idx"), "llm_call_audit", ["agent"], unique=False)
    op.alter_column("llm_call_audit", "status", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("llm_call_audit", "job_id", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("llm_call_audit", "call_index", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("llm_call_audit", "purpose", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("llm_call_audit", "request_type", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("llm_call_audit", "lesson_topic", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("llm_call_audit", "model", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("llm_call_audit", "provider", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("llm_call_audit", "agent", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("llm_call_audit", "created_at", existing_type=postgresql.TIMESTAMP(timezone=True), nullable=False, existing_server_default=sa.text("now()"))
    op.alter_column("llm_call_audit", "id", existing_type=sa.String(), type_=sa.UUID(), existing_nullable=False)

  # Restore dgs_lessons indexes and types when available.
  if "dgs_lessons" in existing_tables:
    if _index_exists(inspector, "dgs_lessons", op.f("ix_dgs_lessons_idempotency_key"), existing_tables):
      op.drop_index(op.f("ix_dgs_lessons_idempotency_key"), table_name="dgs_lessons")
    if not _index_exists(inspector, "dgs_lessons", op.f("dgs_lessons_idempotency_idx"), existing_tables):
      op.create_index(op.f("dgs_lessons_idempotency_idx"), "dgs_lessons", ["idempotency_key"], unique=False)
    op.alter_column("dgs_lessons", "idempotency_key", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("dgs_lessons", "status", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "model_b", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "provider_b", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "model_a", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "provider_a", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "prompt_version", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "schema_version", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "created_at", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "title", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "topic", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_lessons", "lesson_id", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)

  # Restore dgs_jobs indexes and types when available.
  if "dgs_jobs" in existing_tables:
    if _index_exists(inspector, "dgs_jobs", op.f("ix_dgs_jobs_idempotency_key"), existing_tables):
      op.drop_index(op.f("ix_dgs_jobs_idempotency_key"), table_name="dgs_jobs")
    if not _index_exists(inspector, "dgs_jobs", op.f("dgs_jobs_status_created_idx"), existing_tables):
      op.create_index(op.f("dgs_jobs_status_created_idx"), "dgs_jobs", ["status", "created_at"], unique=False)
    if not _index_exists(inspector, "dgs_jobs", op.f("dgs_jobs_idempotency_idx"), existing_tables):
      op.create_index(op.f("dgs_jobs_idempotency_idx"), "dgs_jobs", ["idempotency_key"], unique=False)
    op.alter_column("dgs_jobs", "idempotency_key", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("dgs_jobs", "completed_at", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("dgs_jobs", "updated_at", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_jobs", "created_at", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_jobs", "retry_parent_job_id", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("dgs_jobs", "current_section_title", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("dgs_jobs", "current_section_status", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("dgs_jobs", "subphase", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True)
    op.alter_column("dgs_jobs", "phase", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_jobs", "status", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)
    op.alter_column("dgs_jobs", "job_id", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=False)

  # Recreate meta tables when missing.
  if "llm_audit_meta" not in existing_tables:
    op.create_table(
      "llm_audit_meta",
      sa.Column("key", sa.TEXT(), autoincrement=False, nullable=False),
      sa.Column("value", sa.TEXT(), autoincrement=False, nullable=False),
      sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), autoincrement=False, nullable=False),
      sa.PrimaryKeyConstraint("key", name=op.f("llm_audit_meta_pkey")),
    )

  if "dgs_storage_meta" not in existing_tables:
    op.create_table(
      "dgs_storage_meta",
      sa.Column("key", sa.TEXT(), autoincrement=False, nullable=False),
      sa.Column("value", sa.TEXT(), autoincrement=False, nullable=False),
      sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), autoincrement=False, nullable=False),
      sa.PrimaryKeyConstraint("key", name=op.f("dgs_storage_meta_pkey")),
    )
