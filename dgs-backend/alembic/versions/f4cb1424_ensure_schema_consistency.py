"""ensure_schema_consistency

Revision ID: f4cb1424
Revises: 4c880c225edd
Create Date: 2026-01-26 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4cb1424"
down_revision: str | Sequence[str] | None = "4c880c225edd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema to ensure consistency."""
  conn = op.get_bind()
  inspector = Inspector.from_engine(conn)

  # Check dgs_jobs for missing columns
  if "dgs_jobs" in inspector.get_table_names():
    columns = [c["name"] for c in inspector.get_columns("dgs_jobs")]

    if "expected_sections" not in columns:
      op.add_column("dgs_jobs", sa.Column("expected_sections", sa.Integer(), nullable=True))

    # Check for other potentially missing columns if the table was from an old schema
    if "completed_sections" not in columns:
      op.add_column("dgs_jobs", sa.Column("completed_sections", sa.Integer(), nullable=True))

    if "completed_section_indexes" not in columns:
      # Need to use specific dialect type for JSONB or generic JSON
      from sqlalchemy.dialects.postgresql import JSONB

      op.add_column("dgs_jobs", sa.Column("completed_section_indexes", JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
  """Downgrade schema."""
  # We generally don't remove columns in downgrade if they might contain data
  # and we are just "ensuring consistency", but strictly speaking:
  conn = op.get_bind()
  inspector = Inspector.from_engine(conn)
  if "dgs_jobs" in inspector.get_table_names():
    columns = [c["name"] for c in inspector.get_columns("dgs_jobs")]
    if "expected_sections" in columns:
      op.drop_column("dgs_jobs", "expected_sections")
