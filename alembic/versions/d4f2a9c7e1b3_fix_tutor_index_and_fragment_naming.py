"""fix tutor index names and tutor fragment naming consistency

Revision ID: d4f2a9c7e1b3
Revises: c1e9f7a2b44d
Create Date: 2026-02-11 23:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from app.core.migration_guards import column_exists, constraint_exists, index_exists, table_exists

revision: str = "d4f2a9c7e1b3"
down_revision: str | Sequence[str] | None = "c1e9f7a2b44d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename_index_if_present(*, old_name: str, new_name: str) -> None:
  """Rename an index only when the old name exists and the new name is free."""
  if not index_exists(index_name=old_name):
    return
  if index_exists(index_name=new_name):
    return
  op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")


def _rename_constraint_if_present(*, table_name: str, old_name: str, new_name: str) -> None:
  """Rename a table constraint only when the old name exists and the new name is free."""
  if not table_exists(table_name=table_name):
    return
  if not constraint_exists(constraint_name=old_name):
    return
  if constraint_exists(constraint_name=new_name):
    return
  op.execute(f"ALTER TABLE {table_name} RENAME CONSTRAINT {old_name} TO {new_name}")


def upgrade() -> None:
  if table_exists(table_name="tutors"):
    _rename_index_if_present(old_name="ix_tutor_audios_id", new_name="ix_tutors_id")
    _rename_index_if_present(old_name="ix_tutor_audios_creator_id", new_name="ix_tutors_creator_id")
    _rename_index_if_present(old_name="ix_tutor_audios_job_id", new_name="ix_tutors_job_id")
    _rename_constraint_if_present(table_name="tutors", old_name="tutor_audios_pkey", new_name="tutors_pkey")

  if table_exists(table_name="tutor_audio_fragments") and not table_exists(table_name="tutor_fragments"):
    op.rename_table("tutor_audio_fragments", "tutor_fragments")

  if table_exists(table_name="tutor_fragments"):
    if column_exists(table_name="tutor_fragments", column_name="tutor_audio_id") and not column_exists(table_name="tutor_fragments", column_name="tutor_id"):
      op.alter_column("tutor_fragments", "tutor_audio_id", new_column_name="tutor_id")

    _rename_index_if_present(old_name="ix_tutor_audio_fragments_tutor_audio_id", new_name="ix_tutor_fragments_tutor_id")
    _rename_index_if_present(old_name="ix_tutor_audio_fragments_fragment_id", new_name="ix_tutor_fragments_fragment_id")
    _rename_index_if_present(old_name="ix_tutor_audio_fragments_section_id", new_name="ix_tutor_fragments_section_id")
    _rename_index_if_present(old_name="ix_tutor_audio_fragments_subsection_id", new_name="ix_tutor_fragments_subsection_id")
    _rename_constraint_if_present(table_name="tutor_fragments", old_name="tutor_audio_fragments_pkey", new_name="tutor_fragments_pkey")


def downgrade() -> None:
  if table_exists(table_name="tutor_fragments"):
    _rename_index_if_present(old_name="ix_tutor_fragments_tutor_id", new_name="ix_tutor_audio_fragments_tutor_audio_id")
    _rename_index_if_present(old_name="ix_tutor_fragments_fragment_id", new_name="ix_tutor_audio_fragments_fragment_id")
    _rename_index_if_present(old_name="ix_tutor_fragments_section_id", new_name="ix_tutor_audio_fragments_section_id")
    _rename_index_if_present(old_name="ix_tutor_fragments_subsection_id", new_name="ix_tutor_audio_fragments_subsection_id")
    _rename_constraint_if_present(table_name="tutor_fragments", old_name="tutor_fragments_pkey", new_name="tutor_audio_fragments_pkey")
    if column_exists(table_name="tutor_fragments", column_name="tutor_id") and not column_exists(table_name="tutor_fragments", column_name="tutor_audio_id"):
      op.alter_column("tutor_fragments", "tutor_id", new_column_name="tutor_audio_id")

  if table_exists(table_name="tutor_fragments") and not table_exists(table_name="tutor_audio_fragments"):
    op.rename_table("tutor_fragments", "tutor_audio_fragments")

  if table_exists(table_name="tutors"):
    _rename_index_if_present(old_name="ix_tutors_id", new_name="ix_tutor_audios_id")
    _rename_index_if_present(old_name="ix_tutors_creator_id", new_name="ix_tutor_audios_creator_id")
    _rename_index_if_present(old_name="ix_tutors_job_id", new_name="ix_tutor_audios_job_id")
    _rename_constraint_if_present(table_name="tutors", old_name="tutors_pkey", new_name="tutor_audios_pkey")
