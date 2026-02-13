"""drop_widget_status_columns_followup

Revision ID: 271313020e9b
Revises: 33e34e48df92
Create Date: 2026-02-13 02:12:14.225354

"""

from collections.abc import Sequence

import sqlalchemy as sa
from app.core.migration_guards import column_exists, guarded_add_column, guarded_drop_column, table_exists

# revision identifiers, used by Alembic.
revision: str = "271313020e9b"
down_revision: str | Sequence[str] | None = "33e34e48df92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


WIDGET_STATUS_TABLES = (
  "markdowns",
  "flipcards",
  "translations",
  "fill_blanks",
  "tables_data",
  "compares",
  "swipe_cards",
  "step_flows",
  "ascii_diagrams",
  "checklists",
  "interactive_terminals",
  "terminal_demos",
  "code_editors",
  "treeviews",
  "mcqs",
  "input_lines",
  "free_texts",
)


def upgrade() -> None:
  """Upgrade schema."""
  for table_name in WIDGET_STATUS_TABLES:
    if table_exists(table_name=table_name) and column_exists(table_name=table_name, column_name="status"):
      # destructive: approved (reviewer: TBD)
      guarded_drop_column(table_name, "status")


def downgrade() -> None:
  """Downgrade schema."""
  for table_name in WIDGET_STATUS_TABLES:
    if table_exists(table_name=table_name) and not column_exists(table_name=table_name, column_name="status"):
      guarded_add_column(table_name, sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")))
