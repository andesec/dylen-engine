"""add_coach_tutor_mode_feature_flags

Revision ID: 9ca2ccec4b98
Revises: c0d661232a11
Create Date: 2026-02-10 06:53:18.856484

"""

# revision identifiers, used by Alembic.
revision = "9ca2ccec4b98"
down_revision = "c0d661232a11"
branch_labels = None
depends_on = None


def upgrade() -> None:
  """Upgrade schema."""
  # empty: allow
  # This revision exists so the matching seed script can run through seed_versions tracking.
  return


def downgrade() -> None:
  """Downgrade schema."""
  # No schema changes were introduced in this revision.
  return
