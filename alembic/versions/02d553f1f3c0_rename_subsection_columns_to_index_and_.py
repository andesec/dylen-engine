"""rename subsection columns to index and title

Revision ID: 02d553f1f3c0
Revises: 182e88aeaf64
Create Date: 2026-02-15 08:26:00.869166

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "02d553f1f3c0"
down_revision: str | Sequence[str] | None = "182e88aeaf64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  # Rename columns to match cleaner naming convention
  # This is a rename operation, not add/drop, to preserve existing data

  # First, drop the old unique constraint (references old column name)
  op.drop_constraint("ux_subsections_section_subsection_index", "subsections", type_="unique")

  # Rename columns
  op.alter_column("subsections", "subsection_index", new_column_name="index")
  op.alter_column("subsections", "subsection_title", new_column_name="title")

  # Recreate unique constraint with new column name
  op.create_unique_constraint("ux_subsections_section_subsection_index", "subsections", ["section_id", "index"])


def downgrade() -> None:
  """Downgrade schema."""
  # Reverse the rename operation

  # Drop the new unique constraint
  op.drop_constraint("ux_subsections_section_subsection_index", "subsections", type_="unique")

  # Rename columns back
  op.alter_column("subsections", "index", new_column_name="subsection_index")
  op.alter_column("subsections", "title", new_column_name="subsection_title")

  # Recreate unique constraint with old column names
  op.create_unique_constraint("ux_subsections_section_subsection_index", "subsections", ["section_id", "subsection_index"])
