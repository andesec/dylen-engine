"""Gatherer agent implementation."""

from __future__ import annotations

import logging

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import render_gatherer_prompt
from app.ai.pipeline.contracts import JobContext, PlanSection, SectionDraft
from app.telemetry.context import llm_call_context


class GathererAgent(BaseAgent[PlanSection, SectionDraft]):
  """Collect raw content for a planned section."""

  name = "Gatherer"

  async def run(self, input_data: PlanSection, ctx: JobContext) -> SectionDraft:
    """Generate a draft for a planned section."""
    logger = logging.getLogger(__name__)
    request = ctx.request

    # Use deterministic fixtures for local/test runs when configured.
    dummy_text = self._load_dummy_text()

    if dummy_text is not None:
      # Prefer deterministic fixtures to avoid repeated provider calls in tests.
      raw_text = dummy_text.strip()

      if not raw_text:
        logger.warning(
          "Gatherer dummy response is empty for section %s.", input_data.section_number
        )

      return SectionDraft(
        section_number=input_data.section_number,
        title=input_data.title,
        plan_section=input_data,
        raw_text=raw_text,
        extracted_parts=None,
      )

    # Render the gather prompt and capture the provider call metadata.
    prompt_text = render_gatherer_prompt(request, input_data)
    purpose = f"collect_section_{input_data.section_number}_of_{request.depth}"
    call_index = f"{input_data.section_number}/{request.depth}"

    # Stamp the provider call with agent context so audit logs include request metadata.

    with llm_call_context(
      agent=self.name,
      lesson_topic=request.topic,
      job_id=ctx.job_id,
      purpose=purpose,
      call_index=call_index,
    ):
      response = await self._model.generate(prompt_text)

    self._record_usage(
      agent=self.name, purpose=purpose, call_index=call_index, usage=response.usage
    )

    # Surface empty responses so downstream repair can be triggered.

    if not response.content.strip():
      logger.warning("Gatherer returned empty content for section %s.", input_data.section_number)

    raw_text = response.content.strip()
    section_number = input_data.section_number
    title = input_data.title

    return SectionDraft(
      section_number=section_number,
      title=title,
      plan_section=input_data,
      raw_text=raw_text,
      extracted_parts=None,
    )
