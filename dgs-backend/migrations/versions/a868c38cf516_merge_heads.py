"""merge heads

Revision ID: a868c38cf516
Revises: a1b2c3d4e5f6, 8b4f5e7c8d9a
Create Date: 2026-01-27 18:25:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a868c38cf516"
down_revision: str | None = ("a1b2c3d4e5f6", "1f3c81587763")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  pass


def downgrade() -> None:
  pass
