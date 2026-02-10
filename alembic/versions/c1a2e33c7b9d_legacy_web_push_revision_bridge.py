"""Bridge legacy web push revision id to the current migration chain.

Revision ID: c1a2e33c7b9d
Revises: f97d9c8ef481
Create Date: 2026-02-08 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "c1a2e33c7b9d"
down_revision = "f97d9c8ef481"
branch_labels = None
depends_on = None


def upgrade() -> None:
  """Preserve a removed legacy revision id so existing databases can continue upgrading."""
  # Execute a no-op statement so migration lint treats this bridge revision as intentional.
  op.execute("SELECT 1")


def downgrade() -> None:
  """Leave the legacy bridge as a no-op on downgrade."""
  # Execute a no-op statement because this revision exists only to preserve lineage.
  op.execute("SELECT 1")
