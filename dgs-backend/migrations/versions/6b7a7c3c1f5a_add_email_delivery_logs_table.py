"""Add email delivery logs table with idempotent safeguards.

Revision ID: 6b7a7c3c1f5a
Revises: 459aa50bdc5e
Create Date: 2026-01-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6b7a7c3c1f5a"
down_revision: str | Sequence[str] | None = "459aa50bdc5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  # Inspect current schema to keep migration idempotent on legacy installs.
  inspector = inspect(op.get_bind())
  existing_tables = set(inspector.get_table_names())
  if "email_delivery_logs" not in existing_tables:
    # Create the table when it does not already exist.
    op.create_table(
      "email_delivery_logs",
      sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
      sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
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
    )

  # Ensure expected indexes exist even when the table pre-exists.
  existing_indexes = {index.get("name") for index in inspector.get_indexes("email_delivery_logs")} if "email_delivery_logs" in existing_tables else set()
  for index_name, columns in [
    (op.f("ix_email_delivery_logs_user_id"), ["user_id"]),
    (op.f("ix_email_delivery_logs_to_address"), ["to_address"]),
    (op.f("ix_email_delivery_logs_template_id"), ["template_id"]),
    (op.f("ix_email_delivery_logs_provider_message_id"), ["provider_message_id"]),
    (op.f("ix_email_delivery_logs_provider_request_id"), ["provider_request_id"]),
  ]:
    # Create missing indexes to preserve query performance.
    if index_name not in existing_indexes:
      op.create_index(index_name, "email_delivery_logs", columns, unique=False)


def downgrade() -> None:
  """Downgrade schema."""
  # Inspect schema so downgrade does not fail when the table is missing.
  inspector = inspect(op.get_bind())
  existing_tables = set(inspector.get_table_names())
  if "email_delivery_logs" not in existing_tables:
    # Skip downgrade when the table is already absent.
    return

  op.drop_index(op.f("ix_email_delivery_logs_provider_request_id"), table_name="email_delivery_logs")
  op.drop_index(op.f("ix_email_delivery_logs_provider_message_id"), table_name="email_delivery_logs")
  op.drop_index(op.f("ix_email_delivery_logs_template_id"), table_name="email_delivery_logs")
  op.drop_index(op.f("ix_email_delivery_logs_to_address"), table_name="email_delivery_logs")
  op.drop_index(op.f("ix_email_delivery_logs_user_id"), table_name="email_delivery_logs")
  op.drop_table("email_delivery_logs")
