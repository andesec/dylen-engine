"""Stitcher agent implementation."""

from __future__ import annotations

from app.ai.agents.base import BaseAgent
from app.ai.pipeline.contracts import FinalLesson, JobContext, StructuredSectionBatch


class StitcherAgent(BaseAgent[StructuredSectionBatch, FinalLesson]):
  """Merge structured sections into the final lesson JSON."""

  name = "Stitcher"

  async def run(self, input_data: StructuredSectionBatch, ctx: JobContext) -> FinalLesson:
    """Stitch structured sections into a final lesson payload."""
    sections = sorted(input_data.sections, key=lambda section: section.section_number)
    lesson_json = {"title": ctx.request.topic, "blocks": [section.payload for section in sections]}
    result = self._schema_service.validate_lesson_payload(lesson_json)
    messages = [f"{issue.path}: {issue.message}" for issue in result.issues]
    metadata = {"validation_errors": messages} if messages else None
    return FinalLesson(lesson_json=lesson_json, metadata=metadata)
