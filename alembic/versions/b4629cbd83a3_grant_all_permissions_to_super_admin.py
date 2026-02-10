"""grant_all_permissions_to_super_admin

Revision ID: b4629cbd83a3
Revises: 3055a1cfd37e
Create Date: 2026-02-10 06:23:45.523195

"""

# revision identifiers, used by Alembic.
revision = "b4629cbd83a3"
down_revision = "3055a1cfd37e"
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
