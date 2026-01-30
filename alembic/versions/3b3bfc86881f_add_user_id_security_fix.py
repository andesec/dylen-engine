"""add_user_id_security_fix

Revision ID: 3b3bfc86881f
Revises: f22845381c3c
Create Date: 2026-01-29 12:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3b3bfc86881f'
down_revision: Union[str, None] = 'f22845381c3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dylen_jobs', sa.Column('user_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_dylen_jobs_user_id'), 'dylen_jobs', ['user_id'], unique=False)
    op.add_column('dylen_lessons', sa.Column('user_id', sa.String(), nullable=True))
    op.create_index(op.f('ix_dylen_lessons_user_id'), 'dylen_lessons', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_dylen_lessons_user_id'), table_name='dylen_lessons')
    op.drop_column('dylen_lessons', 'user_id')
    op.drop_index(op.f('ix_dylen_jobs_user_id'), table_name='dylen_jobs')
    op.drop_column('dylen_jobs', 'user_id')
