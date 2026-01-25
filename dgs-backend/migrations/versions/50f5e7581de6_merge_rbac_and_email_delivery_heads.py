"""Merge RBAC and email delivery heads.

Revision ID: 50f5e7581de6
Revises: 5d3a0b7c9f21, 6b7a7c3c1f5a
Create Date: 2026-01-26 01:09:20.246188

"""

from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "50f5e7581de6"
down_revision: str | Sequence[str] | None = ("5d3a0b7c9f21", "6b7a7c3c1f5a")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema by marking a merge point."""
  # No-op merge revision to unify multiple heads.
  return


def downgrade() -> None:
  """Downgrade schema by preserving the merge boundary."""
  # No-op merge revision to preserve branch history.
  return
