"""add_provider_to_users

Revision ID: 459aa50bdc5e
Revises: 241feda2db69
Create Date: 2026-01-21 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "459aa50bdc5e"
down_revision: Union[str, None] = "989029857d49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
  op.add_column("users", sa.Column("provider", sa.String(), nullable=True))


def downgrade() -> None:
  op.drop_column("users", "provider")
