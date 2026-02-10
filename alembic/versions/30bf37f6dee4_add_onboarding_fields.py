"""add_onboarding_fields

Revision ID: 30bf37f6dee4
Revises: 9ca2ccec4b98
Create Date: 2026-02-10 06:53:19.856484

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_guards import guarded_add_column, guarded_drop_column
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "30bf37f6dee4"
down_revision: str | Sequence[str] | None = "9ca2ccec4b98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  # Update the enum only when the enum type exists in the current schema.
  user_status_exists = op.get_bind().execute(text("SELECT 1 FROM pg_type WHERE typname = 'user_status' LIMIT 1")).scalar()
  with op.get_context().autocommit_block():
    if user_status_exists:
      op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'REJECTED'")

  # Add onboarding columns with guards to keep reruns and drifted environments safe.
  guarded_add_column("users", sa.Column("gender", sa.String(), nullable=True))
  guarded_add_column("users", sa.Column("gender_other", sa.String(), nullable=True))
  guarded_add_column("users", sa.Column("occupation", sa.String(), nullable=True))
  guarded_add_column("users", sa.Column("topics_of_interest", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
  guarded_add_column("users", sa.Column("intended_use", sa.String(), nullable=True))
  guarded_add_column("users", sa.Column("intended_use_other", sa.String(), nullable=True))
  guarded_add_column("users", sa.Column("onboarding_completed", sa.Boolean(), server_default=sa.text("false"), nullable=False))
  guarded_add_column("users", sa.Column("accepted_terms_at", sa.DateTime(timezone=True), nullable=True))
  guarded_add_column("users", sa.Column("accepted_privacy_at", sa.DateTime(timezone=True), nullable=True))
  guarded_add_column("users", sa.Column("terms_version", sa.String(), nullable=True))
  guarded_add_column("users", sa.Column("privacy_version", sa.String(), nullable=True))
  guarded_add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade() -> None:
  """Downgrade schema."""
  # Remove columns with guards to keep downgrade resilient on partial schemas.
  guarded_drop_column("users", "updated_at")
  guarded_drop_column("users", "privacy_version")
  guarded_drop_column("users", "terms_version")
  guarded_drop_column("users", "accepted_privacy_at")
  guarded_drop_column("users", "accepted_terms_at")
  guarded_drop_column("users", "onboarding_completed")
  guarded_drop_column("users", "intended_use_other")
  guarded_drop_column("users", "intended_use")
  guarded_drop_column("users", "topics_of_interest")
  guarded_drop_column("users", "occupation")
  guarded_drop_column("users", "gender_other")
  guarded_drop_column("users", "gender")
  # Not downgrading enum as it is not straightforward
