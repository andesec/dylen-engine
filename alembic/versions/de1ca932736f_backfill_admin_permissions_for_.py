"""backfill_admin_permissions_for_superadmin

Revision ID: de1ca932736f
Revises: b4629cbd83a3
Create Date: 2026-02-10 06:28:35.080939

"""

# revision identifiers, used by Alembic.
revision = "de1ca932736f"
down_revision = "b4629cbd83a3"
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
