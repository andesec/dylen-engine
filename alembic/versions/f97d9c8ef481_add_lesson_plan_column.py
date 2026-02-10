"""add_lesson_plan_column

Revision ID: f97d9c8ef481
Revises: 14628b147ec5
Create Date: 2026-02-07 05:15:54.382948

"""

from collections.abc import Sequence

import sqlalchemy as sa
from app.core.migration_guards import guarded_add_column, guarded_drop_column

# revision identifiers, used by Alembic.
revision: str = "f97d9c8ef481"
down_revision: str | Sequence[str] | None = "14628b147ec5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  guarded_add_column("lessons", sa.Column("lesson_plan", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
  """Downgrade schema."""
  guarded_drop_column("lessons", "lesson_plan")
