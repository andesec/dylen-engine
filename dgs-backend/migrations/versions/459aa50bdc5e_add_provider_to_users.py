"""add_provider_to_users

Revision ID: 459aa50bdc5e
Revises: 241feda2db69
Create Date: 2026-01-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "459aa50bdc5e"
down_revision: str | None = "989029857d49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Add the provider column when it is missing."""
  # Inspect schema so duplicate column errors are avoided.
  inspector = inspect(op.get_bind())
  existing_tables = set(inspector.get_table_names())
  if "users" not in existing_tables:
    return

  # Add provider only if it is not already present.
  existing_columns = {str(col.get("name")) for col in inspector.get_columns("users") if col.get("name")}
  if "provider" not in existing_columns:
    op.add_column("users", sa.Column("provider", sa.String(), nullable=True))


def downgrade() -> None:
  """Remove the provider column only when the users table exists."""
  # Inspect schema so downgrade is safe on drifted databases.
  inspector = inspect(op.get_bind())
  existing_tables = set(inspector.get_table_names())
  if "users" not in existing_tables:
    return

  op.drop_column("users", "provider")
