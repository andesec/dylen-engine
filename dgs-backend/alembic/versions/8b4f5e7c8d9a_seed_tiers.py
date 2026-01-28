"""seed subscription tiers

Revision ID: 8b4f5e7c8d9a
Revises: 7a3e4e6e9a6b
Create Date: 2026-01-27 10:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b4f5e7c8d9a"
down_revision: str | None = "7a3e4e6e9a6b"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
  tiers = [
    {"name": "Free", "max_file_upload_kb": 512, "highest_lesson_depth": "highlights", "max_sections_per_lesson": 2, "file_upload_quota": 0, "image_upload_quota": 0, "gen_sections_quota": 20, "coach_mode_enabled": False, "coach_voice_tier": "none"},
    {"name": "Plus", "max_file_upload_kb": 1024, "highest_lesson_depth": "detailed", "max_sections_per_lesson": 6, "file_upload_quota": 5, "image_upload_quota": 5, "gen_sections_quota": 100, "coach_mode_enabled": True, "coach_voice_tier": "device"},
    {"name": "Pro", "max_file_upload_kb": 2048, "highest_lesson_depth": "training", "max_sections_per_lesson": 10, "file_upload_quota": 10, "image_upload_quota": 10, "gen_sections_quota": 250, "coach_mode_enabled": True, "coach_voice_tier": "premium"},
  ]

  conn = op.get_bind()
  for tier in tiers:
    # Check if exists
    exists = conn.execute(sa.text("SELECT 1 FROM subscription_tiers WHERE name = :name"), {"name": tier["name"]}).scalar()
    if not exists:
      conn.execute(
        sa.text("""
                    INSERT INTO subscription_tiers (name, max_file_upload_kb, highest_lesson_depth, max_sections_per_lesson, file_upload_quota, image_upload_quota, gen_sections_quota, coach_mode_enabled, coach_voice_tier)
                    VALUES (:name, :max_file_upload_kb, :highest_lesson_depth, :max_sections_per_lesson, :file_upload_quota, :image_upload_quota, :gen_sections_quota, :coach_mode_enabled, :coach_voice_tier)
                """),
        tier,
      )


def downgrade() -> None:
  pass
