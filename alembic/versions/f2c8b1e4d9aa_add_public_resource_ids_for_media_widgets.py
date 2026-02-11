"""add stable nanoid resource ids for illustrations and fensters

Revision ID: f2c8b1e4d9aa
Revises: d4f2a9c7e1b3
Create Date: 2026-02-11 23:55:00.000000
"""
# backfill: ok

from __future__ import annotations

import secrets
import string
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import column_exists, index_exists, table_exists

revision: str = "f2c8b1e4d9aa"
down_revision: str | Sequence[str] | None = "d4f2a9c7e1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _generate_nanoid(size: int = 21) -> str:
  """Generate a non-sequential public id for externally visible resource identifiers."""
  alphabet = string.ascii_letters + string.digits
  return "".join(secrets.choice(alphabet) for _ in range(size))


def _backfill_public_ids(*, table_name: str, id_column: str, public_id_column: str) -> None:
  """Populate missing public ids with unique nanoids."""
  bind = op.get_bind()
  rows = bind.execute(sa.text(f"SELECT {id_column} FROM {table_name} WHERE {public_id_column} IS NULL")).fetchall()
  for row in rows:
    row_id = row[0]
    while True:
      candidate = _generate_nanoid()
      exists = bind.execute(sa.text(f"SELECT 1 FROM {table_name} WHERE {public_id_column} = :candidate LIMIT 1"), {"candidate": candidate}).first()
      if exists is None:
        bind.execute(sa.text(f"UPDATE {table_name} SET {public_id_column} = :candidate WHERE {id_column} = :row_id"), {"candidate": candidate, "row_id": row_id})
        break


def upgrade() -> None:
  if table_exists(table_name="illustrations"):
    if not column_exists(table_name="illustrations", column_name="public_id"):
      op.add_column("illustrations", sa.Column("public_id", sa.String(), nullable=True))
    _backfill_public_ids(table_name="illustrations", id_column="id", public_id_column="public_id")
    op.alter_column("illustrations", "public_id", nullable=False)
    if not index_exists(index_name="ix_illustrations_public_id"):
      op.create_index("ix_illustrations_public_id", "illustrations", ["public_id"], unique=True)

  if table_exists(table_name="fensters"):
    if not column_exists(table_name="fensters", column_name="public_id"):
      op.add_column("fensters", sa.Column("public_id", sa.String(), nullable=True))
    _backfill_public_ids(table_name="fensters", id_column="fenster_id", public_id_column="public_id")
    op.alter_column("fensters", "public_id", nullable=False)
    if not index_exists(index_name="ix_fensters_public_id"):
      op.create_index("ix_fensters_public_id", "fensters", ["public_id"], unique=True)


def downgrade() -> None:
  if table_exists(table_name="fensters") and column_exists(table_name="fensters", column_name="public_id"):
    if index_exists(index_name="ix_fensters_public_id"):
      op.drop_index("ix_fensters_public_id", table_name="fensters")
    op.drop_column("fensters", "public_id")

  if table_exists(table_name="illustrations") and column_exists(table_name="illustrations", column_name="public_id"):
    if index_exists(index_name="ix_illustrations_public_id"):
      op.drop_index("ix_illustrations_public_id", table_name="illustrations")
    op.drop_column("illustrations", "public_id")
