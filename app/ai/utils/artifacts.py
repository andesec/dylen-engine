from __future__ import annotations

from typing import Any

from app.ai.pipeline.contracts import LessonPlan, StructuredSection


def build_partial_lesson(sections: list[StructuredSection], topic: str) -> dict[str, Any]:
  """Build a partial lesson JSON from the completed sections."""
  # Preserve section order while streaming the latest structured payloads.
  ordered_sections = sorted(sections, key=lambda section: section.section_number)
  return {"title": topic, "blocks": [section.payload for section in ordered_sections]}


def build_failure_snapshot(lesson_plan: LessonPlan | None, draft_artifacts: list[dict[str, Any]], structured_artifacts: list[dict[str, Any]], repair_artifacts: list[dict[str, Any]]) -> dict[str, Any]:
  """Capture the newest artifacts so partial pipeline output is visible during failures."""
  # Surface the newest data only to keep logs readable while still debugging failures.
  plan_payload: dict[str, Any] | None = None

  if lesson_plan is not None:
    plan_payload = lesson_plan.model_dump(mode="python")

  snapshot = {
    "plan": plan_payload,
    "drafts_count": len(draft_artifacts),
    "latest_draft": draft_artifacts[-1] if draft_artifacts else None,
    "structured_count": len(structured_artifacts),
    "latest_structured": structured_artifacts[-1] if structured_artifacts else None,
    "repairs_count": len(repair_artifacts),
    "latest_repair": repair_artifacts[-1] if repair_artifacts else None,
  }
  return snapshot
