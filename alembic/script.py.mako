"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.core.migration_guards import guarded_add_column, guarded_create_check_constraint, guarded_create_foreign_key, guarded_create_index, guarded_create_table, guarded_create_unique_constraint, guarded_drop_column, guarded_drop_constraint, guarded_drop_index, guarded_drop_table
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    # Use guarded_* helpers so migrations are idempotent on existing schemas.
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    # Use guarded_* helpers so downgrade steps are idempotent when re-run.
    ${downgrades if downgrades else "pass"}
