"""Ensure subscription tiers seed data exists.

Revision ID: 7bb0a9b612f5
Revises: f2f00648b393
Create Date: 2026-01-28

How and why:
- Some environments may restore schema-only snapshots or otherwise lose reference
  data. The quota system requires at least a 'Free' tier for user onboarding.
- This migration is idempotent by design and only inserts missing rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7bb0a9b612f5"
down_revision: str | None = "f2f00648b393"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
  """Insert required subscription tiers if they are missing."""
  # Seed only missing rows to avoid overwriting operator customization.
  tiers = [
    {
      "name": "Free",
      "max_file_upload_kb": 512,
      "highest_lesson_depth": "highlights",
      "max_sections_per_lesson": 2,
      "file_upload_quota": 0,
      "image_upload_quota": 0,
      "gen_sections_quota": 20,
      "coach_mode_enabled": False,
      "coach_voice_tier": "none",
      "research_quota": None,
    },
    {
      "name": "Plus",
      "max_file_upload_kb": 1024,
      "highest_lesson_depth": "detailed",
      "max_sections_per_lesson": 6,
      "file_upload_quota": 5,
      "image_upload_quota": 5,
      "gen_sections_quota": 100,
      "coach_mode_enabled": True,
      "coach_voice_tier": "device",
      "research_quota": None,
    },
    {
      "name": "Pro",
      "max_file_upload_kb": 2048,
      "highest_lesson_depth": "training",
      "max_sections_per_lesson": 10,
      "file_upload_quota": 10,
      "image_upload_quota": 10,
      "gen_sections_quota": 250,
      "coach_mode_enabled": True,
      "coach_voice_tier": "premium",
      "research_quota": None,
    },
  ]
  table = sa.table(
    "subscription_tiers",
    sa.column("name"),
    sa.column("max_file_upload_kb"),
    sa.column("highest_lesson_depth"),
    sa.column("max_sections_per_lesson"),
    sa.column("file_upload_quota"),
    sa.column("image_upload_quota"),
    sa.column("gen_sections_quota"),
    sa.column("coach_mode_enabled"),
    sa.column("coach_voice_tier"),
    sa.column("research_quota"),
  )
  statement = insert(table).values(tiers).on_conflict_do_nothing(index_elements=["name"])
  op.execute(statement)


def downgrade() -> None:
  """Downgrades are intentionally a no-op for seed data."""
  # Seed rows may have been modified by operators; do not delete on downgrade.
  return
