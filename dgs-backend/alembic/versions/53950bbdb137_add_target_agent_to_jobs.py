"""Add target_agent to jobs

Revision ID: 53950bbdb137
Revises: 3301fadf083b
Create Date: 2026-01-27 22:49:37.945629

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "53950bbdb137"
down_revision: str | Sequence[str] | None = "3301fadf083b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  op.add_column("dgs_jobs", sa.Column("target_agent", sa.String(), nullable=True))


def downgrade() -> None:
  """Downgrade schema."""
  op.drop_column("dgs_jobs", "target_agent")
