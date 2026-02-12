"""update_runtime_config_after_env_refactor

Revision ID: 3c0d47535e71
Revises: f2c8b1e4d9aa
Create Date: 2026-02-11 23:55:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c0d47535e71"
down_revision: str | Sequence[str] | None = "f2c8b1e4d9aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  # Use guarded_* helpers so migrations are idempotent on existing schemas.
  bind = op.get_bind()
  bind.execute(sa.text("DELETE FROM runtime_config_values WHERE key IN ('jobs.ttl_seconds', 'jobs.max_retries')"))


def downgrade() -> None:
  """Downgrade schema."""
  # Use guarded_* helpers so downgrade steps are idempotent when re-run.
  return
