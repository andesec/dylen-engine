"""add learning_focus and section_count to lesson_requests

Revision ID: 69qeq3n651oz
Revises: a73c0f9a24a9
Create Date: 2026-02-15 11:17:09.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "69qeq3n651oz"
down_revision: str | Sequence[str] | None = "a73c0f9a24a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  # Add new columns
  op.add_column("lesson_requests", sa.Column("learning_focus", sa.String(), nullable=True))
  op.add_column("lesson_requests", sa.Column("section_count", sa.Integer(), nullable=False, server_default="2"))

  # Migrate existing depth values to section_count
  # highlights -> 2, detailed -> 4, training -> 5
  op.execute("""
    UPDATE lesson_requests 
    SET section_count = CASE 
      WHEN depth = 'highlights' THEN 2
      WHEN depth = 'detailed' THEN 4
      WHEN depth = 'training' THEN 5
      ELSE 2
    END
  """)

  # Drop old depth column
  op.drop_column("lesson_requests", "depth")


def downgrade() -> None:
  """Downgrade schema."""
  # Add back depth column
  op.add_column("lesson_requests", sa.Column("depth", sa.String(), nullable=False, server_default="highlights"))

  # Migrate section_count back to depth
  # 1-2 -> highlights, 3-4 -> detailed, 5 -> training
  op.execute("""
    UPDATE lesson_requests 
    SET depth = CASE 
      WHEN section_count <= 2 THEN 'highlights'
      WHEN section_count <= 4 THEN 'detailed'
      ELSE 'training'
    END
  """)

  # Drop new columns
  op.drop_column("lesson_requests", "section_count")
  op.drop_column("lesson_requests", "learning_focus")
