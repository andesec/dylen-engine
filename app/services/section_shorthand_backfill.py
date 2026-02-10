"""Backfill helpers for section shorthand content."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.database import get_session_factory
from app.schema.lessons import Section
from app.services.section_shorthand import build_section_shorthand_content
from sqlalchemy import select


@dataclass(frozen=True)
class SectionShorthandBackfillResult:
  """Outcome summary for a shorthand backfill request."""

  updated_section_ids: list[int]
  missing_section_ids: list[int]
  failed: dict[int, str]


async def backfill_section_shorthand(section_ids: list[int]) -> SectionShorthandBackfillResult:
  """Convert section content JSON into canonical shorthand for selected section ids."""
  normalized_ids: list[int] = []
  for section_id in section_ids:
    if section_id <= 0:
      continue
    if section_id not in normalized_ids:
      normalized_ids.append(section_id)
  session_factory = get_session_factory()
  if session_factory is None:
    raise RuntimeError("Database session factory unavailable for section shorthand backfill.")
  if not normalized_ids:
    return SectionShorthandBackfillResult(updated_section_ids=[], missing_section_ids=[], failed={})
  updated_section_ids: list[int] = []
  missing_section_ids: list[int] = []
  failed: dict[int, str] = {}
  async with session_factory() as session:
    rows_result = await session.execute(select(Section).where(Section.section_id.in_(normalized_ids)))
    sections = rows_result.scalars().all()
    section_map = {row.section_id: row for row in sections}
    for section_id in normalized_ids:
      row = section_map.get(section_id)
      if row is None:
        missing_section_ids.append(section_id)
        continue
      if not isinstance(row.content, dict):
        failed[section_id] = "Section content is missing or not a JSON object."
        continue
      try:
        row.content_shorthand = build_section_shorthand_content(row.content)
        session.add(row)
        updated_section_ids.append(section_id)
      except Exception as exc:  # noqa: BLE001
        failed[section_id] = str(exc)
    await session.commit()
  return SectionShorthandBackfillResult(updated_section_ids=updated_section_ids, missing_section_ids=missing_section_ids, failed=failed)
