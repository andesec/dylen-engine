"""create_fenster_widgets_table

Revision ID: 3301fadf083b
Revises: f2f00648b393
Create Date: 2026-01-27 22:28:55.269925

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3301fadf083b'
down_revision: Union[str, Sequence[str], None] = 'f2f00648b393'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'fenster_widgets',
        sa.Column('fenster_id', sa.Uuid(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('fenster_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('fenster_widgets')
