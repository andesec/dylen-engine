"""baseline_schema

Revision ID: 4c880c225edd
Revises:
Create Date: 2026-01-26 03:53:39.577695

"""

# destructive: approved
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c880c225edd"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  conn = op.get_bind()
  inspector = Inspector.from_engine(conn)
  tables = inspector.get_table_names()

  # Drop legacy meta tables if they exist
  if "llm_audit_meta" in tables:
    op.drop_table("llm_audit_meta")
  if "dgs_storage_meta" in tables:
    op.drop_table("dgs_storage_meta")

  # Create dgs_jobs if not exists
  if "dgs_jobs" not in tables:
    op.create_table(
      "dgs_jobs",
      sa.Column("job_id", sa.String(), nullable=False),
      sa.Column("request", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
      sa.Column("status", sa.String(), nullable=False),
      sa.Column("phase", sa.String(), nullable=False),
      sa.Column("subphase", sa.String(), nullable=True),
      sa.Column("expected_sections", sa.Integer(), nullable=True),
      sa.Column("completed_sections", sa.Integer(), nullable=True),
      sa.Column("completed_section_indexes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
      sa.Column("current_section_index", sa.Integer(), nullable=True),
      sa.Column("current_section_status", sa.String(), nullable=True),
      sa.Column("current_section_retry_count", sa.Integer(), nullable=True),
      sa.Column("current_section_title", sa.String(), nullable=True),
      sa.Column("retry_count", sa.Integer(), nullable=True),
      sa.Column("max_retries", sa.Integer(), nullable=True),
      sa.Column("retry_sections", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
      sa.Column("retry_agents", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
      sa.Column("retry_parent_job_id", sa.String(), nullable=True),
      sa.Column("total_steps", sa.Integer(), nullable=True),
      sa.Column("completed_steps", sa.Integer(), nullable=True),
      sa.Column("progress", sa.Double(), nullable=True),
      sa.Column("logs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
      sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
      sa.Column("artifacts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
      sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
      sa.Column("cost", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
      sa.Column("created_at", sa.String(), nullable=False),
      sa.Column("updated_at", sa.String(), nullable=False),
      sa.Column("completed_at", sa.String(), nullable=True),
      sa.Column("ttl", sa.Integer(), nullable=True),
      sa.Column("idempotency_key", sa.String(), nullable=True),
      sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(op.f("ix_dgs_jobs_idempotency_key"), "dgs_jobs", ["idempotency_key"], unique=False)
    op.create_index("dgs_jobs_status_created_idx", "dgs_jobs", ["status", "created_at"], unique=False)

  # Create dgs_lessons if not exists
  if "dgs_lessons" not in tables:
    op.create_table(
      "dgs_lessons",
      sa.Column("lesson_id", sa.String(), nullable=False),
      sa.Column("topic", sa.String(), nullable=False),
      sa.Column("title", sa.String(), nullable=False),
      sa.Column("created_at", sa.String(), nullable=False),
      sa.Column("schema_version", sa.String(), nullable=False),
      sa.Column("prompt_version", sa.String(), nullable=False),
      sa.Column("provider_a", sa.String(), nullable=False),
      sa.Column("model_a", sa.String(), nullable=False),
      sa.Column("provider_b", sa.String(), nullable=False),
      sa.Column("model_b", sa.String(), nullable=False),
      sa.Column("lesson_json", sa.Text(), nullable=False),
      sa.Column("status", sa.String(), nullable=False),
      sa.Column("latency_ms", sa.Integer(), nullable=False),
      sa.Column("idempotency_key", sa.String(), nullable=True),
      sa.Column("tags", sa.ARRAY(sa.Text()), nullable=True),
      sa.PrimaryKeyConstraint("lesson_id"),
    )
    op.create_index(op.f("ix_dgs_lessons_idempotency_key"), "dgs_lessons", ["idempotency_key"], unique=False)

  # Create users if not exists
  if "users" not in tables:
    op.create_table(
      "users",
      sa.Column("id", sa.UUID(), nullable=False),
      sa.Column("firebase_uid", sa.String(), nullable=False),
      sa.Column("email", sa.String(), nullable=False),
      sa.Column("full_name", sa.String(), nullable=True),
      sa.Column("provider", sa.String(), nullable=True),
      sa.Column("profession", sa.String(), nullable=True),
      sa.Column("city", sa.String(), nullable=True),
      sa.Column("country", sa.String(), nullable=True),
      sa.Column("age", sa.Integer(), nullable=True),
      sa.Column("photo_url", sa.String(), nullable=True),
      sa.Column("is_approved", sa.Boolean(), nullable=False, server_default="false"),
      sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
      sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
      sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_firebase_uid"), "users", ["firebase_uid"], unique=True)

  # Create llm_audit_logs if not exists
  if "llm_audit_logs" not in tables:
    op.create_table(
      "llm_audit_logs",
      sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
      sa.Column("user_id", sa.UUID(), nullable=False),
      sa.Column("prompt_summary", sa.Text(), nullable=True),
      sa.Column("model_name", sa.String(), nullable=False),
      sa.Column("tokens_used", sa.Integer(), nullable=True),
      sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
      sa.Column("status", sa.String(), nullable=True),
      sa.PrimaryKeyConstraint("id"),
      sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

  # Create email_delivery_logs if not exists
  if "email_delivery_logs" not in tables:
    op.create_table(
      "email_delivery_logs",
      sa.Column("id", sa.UUID(), nullable=False),
      sa.Column("user_id", sa.UUID(), nullable=True),
      sa.Column("to_address", sa.String(), nullable=False),
      sa.Column("template_id", sa.String(), nullable=False),
      sa.Column("placeholders", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
      sa.Column("provider", sa.String(), nullable=False),
      sa.Column("provider_message_id", sa.String(), nullable=True),
      sa.Column("provider_request_id", sa.String(), nullable=True),
      sa.Column("provider_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
      sa.Column("status", sa.String(), nullable=False),
      sa.Column("error_message", sa.Text(), nullable=True),
      sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
      sa.PrimaryKeyConstraint("id"),
      sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index(op.f("ix_email_delivery_logs_provider_message_id"), "email_delivery_logs", ["provider_message_id"], unique=False)
    op.create_index(op.f("ix_email_delivery_logs_provider_request_id"), "email_delivery_logs", ["provider_request_id"], unique=False)
    op.create_index(op.f("ix_email_delivery_logs_template_id"), "email_delivery_logs", ["template_id"], unique=False)
    op.create_index(op.f("ix_email_delivery_logs_to_address"), "email_delivery_logs", ["to_address"], unique=False)
    op.create_index(op.f("ix_email_delivery_logs_user_id"), "email_delivery_logs", ["user_id"], unique=False)

  # Create llm_call_audit if not exists
  if "llm_call_audit" not in tables:
    op.create_table(
      "llm_call_audit",
      sa.Column("id", sa.String(), nullable=False),
      sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
      sa.Column("timestamp_request", sa.DateTime(timezone=True), nullable=False),
      sa.Column("timestamp_response", sa.DateTime(timezone=True), nullable=True),
      sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
      sa.Column("duration_ms", sa.Integer(), nullable=False),
      sa.Column("agent", sa.String(), nullable=False),
      sa.Column("provider", sa.String(), nullable=False),
      sa.Column("model", sa.String(), nullable=False),
      sa.Column("lesson_topic", sa.String(), nullable=True),
      sa.Column("request_payload", sa.Text(), nullable=False),
      sa.Column("response_payload", sa.Text(), nullable=True),
      sa.Column("prompt_tokens", sa.Integer(), nullable=True),
      sa.Column("completion_tokens", sa.Integer(), nullable=True),
      sa.Column("total_tokens", sa.Integer(), nullable=True),
      sa.Column("request_type", sa.String(), nullable=False),
      sa.Column("purpose", sa.String(), nullable=True),
      sa.Column("call_index", sa.String(), nullable=True),
      sa.Column("job_id", sa.String(), nullable=True),
      sa.Column("status", sa.String(), nullable=False),
      sa.Column("error_message", sa.Text(), nullable=True),
      sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
  """Downgrade schema."""
  op.drop_table("llm_call_audit")
  op.drop_table("dgs_lessons")
  op.drop_table("dgs_jobs")
