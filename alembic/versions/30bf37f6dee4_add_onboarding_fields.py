"""add_onboarding_fields

Revision ID: 30bf37f6dee4
Revises: merge_heads_20260130
Create Date: 2026-02-01 12:19:56.672083

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '30bf37f6dee4'
down_revision: Union[str, Sequence[str], None] = 'merge_heads_20260130'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Update Enum
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'REJECTED'")

    # Add columns
    op.add_column('users', sa.Column('gender', sa.String(), nullable=True))
    op.add_column('users', sa.Column('gender_other', sa.String(), nullable=True))
    op.add_column('users', sa.Column('occupation', sa.String(), nullable=True))
    op.add_column('users', sa.Column('topics_of_interest', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('users', sa.Column('intended_use', sa.String(), nullable=True))
    op.add_column('users', sa.Column('intended_use_other', sa.String(), nullable=True))
    op.add_column('users', sa.Column('onboarding_completed', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('users', sa.Column('accepted_terms_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('accepted_privacy_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('terms_version', sa.String(), nullable=True))
    op.add_column('users', sa.Column('privacy_version', sa.String(), nullable=True))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'updated_at')
    op.drop_column('users', 'privacy_version')
    op.drop_column('users', 'terms_version')
    op.drop_column('users', 'accepted_privacy_at')
    op.drop_column('users', 'accepted_terms_at')
    op.drop_column('users', 'onboarding_completed')
    op.drop_column('users', 'intended_use_other')
    op.drop_column('users', 'intended_use')
    op.drop_column('users', 'topics_of_interest')
    op.drop_column('users', 'occupation')
    op.drop_column('users', 'gender_other')
    op.drop_column('users', 'gender')
    # Not downgrading enum as it is not straightforward
