"""Planner agent implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import format_schema_block, render_planner_prompt
from app.ai.pipeline.contracts import GenerationRequest, JobContext, LessonPlan


class PlannerAgent(BaseAgent[GenerationRequest, LessonPlan]):
  """Generate a lesson plan before gathering content."""

  name = "Planner"

  async def run(self, input_data: GenerationRequest, ctx: JobContext) -> LessonPlan:
    """Plan the lesson sections and per-section gather prompts."""
    logger = logging.getLogger(__name__)
    dummy_json = self._load_dummy_json()
    if dummy_json is not None:
      # Use deterministic fixture output when configured to avoid provider calls.
      plan = LessonPlan.model_validate(dummy_json)
      if len(plan.sections) != input_data.depth:
        message = f"Planner dummy returned {len(plan.sections)} sections; expected {input_data.depth}."
        logger.error(message)
        raise RuntimeError(message)
      return plan
    prompt_text = render_planner_prompt(input_data)
    schema = LessonPlan.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")
    if self._model.supports_structured_output:
      schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
      response = await self._model.generate_structured(prompt_text, schema)
      self._record_usage(agent=self.name, purpose="plan_lesson", call_index="1/1", usage=response.usage)
      plan_json = response.content
    else:
      prompt_parts = [
        prompt_text,
        format_schema_block(schema, label="JSON SCHEMA (Lesson Plan)"),
        "Output ONLY valid JSON.",
      ]
      prompt_with_schema = "\n\n".join(prompt_parts)
      raw = await self._model.generate(prompt_with_schema)
      self._record_usage(agent=self.name, purpose="plan_lesson", call_index="1/1", usage=raw.usage)
      try:
        cleaned = self._model.strip_json_fences(raw.content)
        plan_json = cast(dict[str, Any], json.loads(cleaned))
      except json.JSONDecodeError as exc:
        logger.error("Planner failed to parse JSON: %s", exc)
        raise RuntimeError(f"Failed to parse planner JSON: {exc}") from exc

    plan = LessonPlan.model_validate(plan_json)
    if len(plan.sections) != input_data.depth:
      message = f"Planner returned {len(plan.sections)} sections; expected {input_data.depth}."
      logger.error(message)
      raise RuntimeError(message)
    return plan
