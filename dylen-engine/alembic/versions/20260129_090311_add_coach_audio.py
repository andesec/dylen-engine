"""add_coach_audio

Revision ID: 20260129_090311
Revises: 6f6e9c1c0c0a
Create Date: 2026-01-29 09:03:11.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260129_090311"
down_revision: str | Sequence[str] | None = "6f6e9c1c0c0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  """Upgrade schema."""
  op.create_table(
    "coach_audios",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("job_id", sa.String(), nullable=False),
    sa.Column("section_number", sa.Integer(), nullable=False),
    sa.Column("subsection_index", sa.Integer(), nullable=False),
    sa.Column("text_content", sa.Text(), nullable=True),
    sa.Column("audio_data", sa.LargeBinary(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
    sa.PrimaryKeyConstraint("id"),
  )
  op.create_index(op.f("ix_coach_audios_id"), "coach_audios", ["id"], unique=False)
  op.create_index(op.f("ix_coach_audios_job_id"), "coach_audios", ["job_id"], unique=False)


def downgrade() -> None:
  """Downgrade schema."""
  op.drop_index(op.f("ix_coach_audios_job_id"), table_name="coach_audios")
  op.drop_index(op.f("ix_coach_audios_id"), table_name="coach_audios")
  op.drop_table("coach_audios")
