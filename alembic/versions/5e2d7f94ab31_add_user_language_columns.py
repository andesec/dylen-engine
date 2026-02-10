"""Add primary and secondary onboarding language columns to users.

Revision ID: 5e2d7f94ab31
Revises: 1b4e6f7a9c21
Create Date: 2026-02-09 21:05:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from app.core.migration_guards import guarded_add_column, guarded_create_check_constraint, guarded_drop_column, guarded_drop_constraint

# revision identifiers, used by Alembic.
revision = "5e2d7f94ab31"
down_revision = "1b4e6f7a9c21"
branch_labels = None
depends_on = None

_ALLOWED_LANGUAGE_CODES_SQL = "('en','es','fr','de','zh','ja','ko','pt','it','ru','ar','hi','bn','tr','vi','pl','nl','id')"
_PRIMARY_LANGUAGE_CONSTRAINT = "ck_users_primary_language_supported"
_SECONDARY_LANGUAGE_CONSTRAINT = "ck_users_secondary_language_supported"


def upgrade() -> None:
  """Upgrade schema."""
  # Add primary/secondary language columns for onboarding personalization.
  guarded_add_column("users", sa.Column("primary_language", sa.String(), nullable=True))
  guarded_add_column("users", sa.Column("secondary_language", sa.String(), nullable=True))

  # Enforce that stored values are in the Gemini-supported code set when present.
  guarded_create_check_constraint(_PRIMARY_LANGUAGE_CONSTRAINT, "users", f"primary_language IS NULL OR primary_language IN {_ALLOWED_LANGUAGE_CODES_SQL}")
  guarded_create_check_constraint(_SECONDARY_LANGUAGE_CONSTRAINT, "users", f"secondary_language IS NULL OR secondary_language IN {_ALLOWED_LANGUAGE_CODES_SQL}")


def downgrade() -> None:
  """Downgrade schema."""
  guarded_drop_constraint(_SECONDARY_LANGUAGE_CONSTRAINT, "users", type_="check")
  guarded_drop_constraint(_PRIMARY_LANGUAGE_CONSTRAINT, "users", type_="check")
  guarded_drop_column("users", "secondary_language")
  guarded_drop_column("users", "primary_language")
