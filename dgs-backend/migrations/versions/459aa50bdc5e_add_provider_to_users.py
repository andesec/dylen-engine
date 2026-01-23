"""add_provider_to_users

Revision ID: 459aa50bdc5e
Revises: 241feda2db69
Create Date: 2026-01-21 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "459aa50bdc5e"
down_revision: str | None = "989029857d49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  op.add_column("users", sa.Column("provider", sa.String(), nullable=True))


def downgrade() -> None:
  op.drop_column("users", "provider")
