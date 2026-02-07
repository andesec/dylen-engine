"""remove_lesson_json

Revision ID: 14628b147ec5
Revises: b94c8e7d2f1a
Create Date: 2026-02-07 04:27:18.623288

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_add_column, guarded_drop_column

# revision identifiers, used by Alembic.
revision: str = "14628b147ec5"
down_revision: str | Sequence[str] | None = "b94c8e7d2f1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  # destructive: approved
  guarded_drop_column("lessons", "lesson_json")


def downgrade() -> None:
  """Downgrade schema."""
  guarded_add_column(op, "lessons", sa.Column("lesson_json", sa.Text(), nullable=True))
