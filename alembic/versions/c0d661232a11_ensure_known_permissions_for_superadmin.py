"""ensure_known_permissions_for_superadmin

Revision ID: c0d661232a11
Revises: de1ca932736f
Create Date: 2026-02-10 06:31:30.430043

"""

# revision identifiers, used by Alembic.
revision = "c0d661232a11"
down_revision = "de1ca932736f"
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
