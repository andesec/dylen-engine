"""Add email delivery logs table.

Revision ID: 6b7a7c3c1f5a
Revises: 459aa50bdc5e
Create Date: 2026-01-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6b7a7c3c1f5a"
down_revision: str | Sequence[str] | None = "459aa50bdc5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
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
  op.create_index(op.f("ix_email_delivery_logs_user_id"), "email_delivery_logs", ["user_id"], unique=False)
  op.create_index(op.f("ix_email_delivery_logs_to_address"), "email_delivery_logs", ["to_address"], unique=False)
  op.create_index(op.f("ix_email_delivery_logs_template_id"), "email_delivery_logs", ["template_id"], unique=False)
  op.create_index(op.f("ix_email_delivery_logs_provider_message_id"), "email_delivery_logs", ["provider_message_id"], unique=False)
  op.create_index(op.f("ix_email_delivery_logs_provider_request_id"), "email_delivery_logs", ["provider_request_id"], unique=False)


def downgrade() -> None:
  """Downgrade schema."""
  op.drop_index(op.f("ix_email_delivery_logs_provider_request_id"), table_name="email_delivery_logs")
  op.drop_index(op.f("ix_email_delivery_logs_provider_message_id"), table_name="email_delivery_logs")
  op.drop_index(op.f("ix_email_delivery_logs_template_id"), table_name="email_delivery_logs")
  op.drop_index(op.f("ix_email_delivery_logs_to_address"), table_name="email_delivery_logs")
  op.drop_index(op.f("ix_email_delivery_logs_user_id"), table_name="email_delivery_logs")
  op.drop_table("email_delivery_logs")
