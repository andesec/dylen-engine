"""Add profile fields to users with idempotent safeguards.

Revision ID: 241feda2db69
Revises:
Create Date: 2026-01-19 21:17:48.385511

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "241feda2db69"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Add new profile fields without failing on existing columns."""
  # Inspect current schema so the migration is safe to rerun.
  inspector = inspect(op.get_bind())
  existing_tables = set(inspector.get_table_names())
  # Skip column changes if the users table does not exist.
  if "users" not in existing_tables:
    return

  # Load column names so we can add only missing fields.
  existing_columns = {str(col.get("name")) for col in inspector.get_columns("users") if col.get("name")}
  if "profession" not in existing_columns:
    op.add_column("users", sa.Column("profession", sa.String(), nullable=True))

  if "city" not in existing_columns:
    op.add_column("users", sa.Column("city", sa.String(), nullable=True))

  if "country" not in existing_columns:
    op.add_column("users", sa.Column("country", sa.String(), nullable=True))

  if "age" not in existing_columns:
    op.add_column("users", sa.Column("age", sa.Integer(), nullable=True))

  if "photo_url" not in existing_columns:
    op.add_column("users", sa.Column("photo_url", sa.String(), nullable=True))


def downgrade() -> None:
  """Remove profile fields only when the users table exists."""
  # Inspect schema so we don't fail if tables were never created.
  inspector = inspect(op.get_bind())
  existing_tables = set(inspector.get_table_names())
  if "users" not in existing_tables:
    return

  # Drop columns in reverse order to minimize dependency issues.
  op.drop_column("users", "photo_url")
  op.drop_column("users", "age")
  op.drop_column("users", "country")
  op.drop_column("users", "city")
  op.drop_column("users", "profession")
