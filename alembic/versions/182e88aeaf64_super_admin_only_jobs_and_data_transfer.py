"""super_admin_only_jobs_and_data_transfer

Revision ID: 182e88aeaf64
Revises: 939e5e69b348
Create Date: 2026-02-15 05:10:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "182e88aeaf64"
down_revision: str | Sequence[str] | None = "939e5e69b348"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  # empty: allow
  # No schema changes in this revision. RBAC data changes are applied in scripts/seeds/182e88aeaf64.py.
  return


def downgrade() -> None:
  """Downgrade schema."""
  # No schema changes to reverse for this revision.
  return
