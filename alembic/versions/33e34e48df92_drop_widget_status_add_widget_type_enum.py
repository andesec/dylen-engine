"""drop_widget_status_add_widget_type_enum

Revision ID: 33e34e48df92
Revises: bf687b4cfbed
Create Date: 2026-02-13 01:57:39.885642

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import column_exists, guarded_add_column, guarded_drop_column, table_exists
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "33e34e48df92"
down_revision: str | Sequence[str] | None = "bf687b4cfbed"
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


WIDGET_TYPE_ENUM_VALUES = (
  "markdown",
  "flipcards",
  "tr",
  "fillblank",
  "table",
  "compare",
  "swipecards",
  "freeText",
  "inputLine",
  "stepFlow",
  "asciiDiagram",
  "checklist",
  "interactiveTerminal",
  "terminalDemo",
  "codeEditor",
  "treeview",
  "mcqs",
  "fenster",
  "illustration",
)


def _normalize_widget_type_values() -> None:
  if not table_exists(table_name="subsection_widgets"):
    return
  op.execute(sa.text("UPDATE subsection_widgets SET widget_type = btrim(widget_type) WHERE widget_type IS NOT NULL"))
  mappings = {
    "freetext": "freeText",
    "inputline": "inputLine",
    "stepflow": "stepFlow",
    "asciidiagram": "asciiDiagram",
    "interactiveterminal": "interactiveTerminal",
    "terminaldemo": "terminalDemo",
    "codeeditor": "codeEditor",
    "swipecard": "swipecards",
    "swipecards": "swipecards",
    "flip": "flipcards",
    "translation": "tr",
    "translations": "tr",
    "fill_blank": "fillblank",
    "fillblanks": "fillblank",
    "fill_blanks": "fillblank",
    "tabledata": "table",
    "tables_data": "table",
    "comparetable": "compare",
    "swipe_cards": "swipecards",
    "step_flows": "stepFlow",
    "ascii_diagrams": "asciiDiagram",
    "interactive_terminals": "interactiveTerminal",
    "terminal_demos": "terminalDemo",
    "code_editors": "codeEditor",
    "treeviews": "treeview",
  }
  for legacy_value, canonical in mappings.items():
    op.execute(sa.text("UPDATE subsection_widgets SET widget_type = :canonical WHERE lower(widget_type) = :legacy").bindparams(canonical=canonical, legacy=legacy_value))
  allowed_values = [value.lower() for value in WIDGET_TYPE_ENUM_VALUES]
  op.execute(sa.text("UPDATE subsection_widgets SET widget_type = :fallback WHERE widget_type IS NULL OR lower(widget_type) NOT IN :allowed").bindparams(sa.bindparam("allowed", expanding=True), fallback="markdown", allowed=allowed_values))


def upgrade() -> None:
  """Upgrade schema."""
  for table_name in WIDGET_STATUS_TABLES:
    if table_exists(table_name=table_name) and column_exists(table_name=table_name, column_name="status"):
      # destructive: approved (reviewer: TBD)
      guarded_drop_column(table_name, "status")

  if table_exists(table_name="subsection_widgets") and column_exists(table_name="subsection_widgets", column_name="widget_type"):
    widget_type_enum = postgresql.ENUM(*WIDGET_TYPE_ENUM_VALUES, name="subsection_widget_type")
    widget_type_enum.create(op.get_bind(), checkfirst=True)
    _normalize_widget_type_values()
    # backfill: ok (normalized to allowed values before enum cast)
    # type-change: approved (expand: create enum + normalize; contract: cast back in downgrade)
    op.alter_column("subsection_widgets", "widget_type", type_=widget_type_enum, existing_type=sa.String(), postgresql_using="widget_type::text::subsection_widget_type", nullable=False)


def downgrade() -> None:
  """Downgrade schema."""
  if table_exists(table_name="subsection_widgets") and column_exists(table_name="subsection_widgets", column_name="widget_type"):
    op.alter_column("subsection_widgets", "widget_type", type_=sa.String(), existing_type=postgresql.ENUM(*WIDGET_TYPE_ENUM_VALUES, name="subsection_widget_type"), postgresql_using="widget_type::text", nullable=False)
    widget_type_enum = postgresql.ENUM(*WIDGET_TYPE_ENUM_VALUES, name="subsection_widget_type")
    widget_type_enum.drop(op.get_bind(), checkfirst=True)

  for table_name in WIDGET_STATUS_TABLES:
    if table_exists(table_name=table_name) and not column_exists(table_name=table_name, column_name="status"):
      guarded_add_column(table_name, sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'pending'")))
