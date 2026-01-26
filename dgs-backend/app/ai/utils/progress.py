from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SectionStatus = Literal["generating", "retrying", "completed"]


@dataclass(frozen=True)
class SectionProgressUpdate:
  """Section-level metadata for streaming job progress."""

  index: int
  title: str | None
  status: SectionStatus
  retry_count: int | None = None
  completed_sections: int | None = None


def create_section_progress(
  section_index: int,
  *,
  title: str | None,
  status: SectionStatus,
  retry_count: int | None = None,
  completed_sections: int | None = None,
) -> SectionProgressUpdate:
  """Normalize section progress updates with 0-based indexing."""
  # Convert 1-based section numbers to the 0-based indices expected by the client.
  zero_based_index = section_index - 1
  return SectionProgressUpdate(
    index=zero_based_index, title=title, status=status, retry_count=retry_count, completed_sections=completed_sections
  )
