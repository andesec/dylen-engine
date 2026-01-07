"""Planner agent implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from app.ai.agents.base import BaseAgent
from app.ai.pipeline.contracts import GenerationRequest, LessonPlan, JobContext
from app.ai.agents.prompts import render_planner_prompt, format_schema_block
from pydantic import ValidationError


def _repair_planner_json(plan_json: dict[str, Any]) -> dict[str, Any]:
  """Repair JSON by converting between strings and lists of strings."""
  if "sections" in plan_json:
    for section in plan_json["sections"]:
      # Convert string to list for fields that should be lists
      for field in ["data_collection_points"]:
        if field in section and isinstance(section[field], str):
          section[field] = [section[field]]
      
      # Convert array to string for fields that should be strings.
      for field in ["data_collection_points", "continuity_note"]:
        for k, v in section[field] :
          if isinstance(v, list):
            section[field] = ".".join(str(x) for x in v)
      
      # Handle subsections
      if "subsections" in section:
        for subsection in section["subsections"]:
          if "planned_widgets" in subsection and isinstance(subsection["planned_widgets"], str):
            subsection["planned_widgets"] = [subsection["planned_widgets"]]
  
  return plan_json


class PlannerAgent(BaseAgent[GenerationRequest, LessonPlan]):
  """Generate a lesson plan before gathering content."""

  name = "Planner"

  async def run(self, input_data: GenerationRequest, ctx: JobContext) -> LessonPlan:
    """Plan the lesson sections and per-section gather prompts."""
    logger = logging.getLogger(__name__)
    
    dummy_json = self._load_dummy_json()
    if dummy_json is not None:
      logger.info("Using deterministic dummy output for Planner")
      # Use deterministic fixture output when configured to avoid provider calls.
      plan = LessonPlan.model_validate(dummy_json)
      return plan
    
    prompt_text = render_planner_prompt(input_data)
    schema = LessonPlan.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")
    
    if self._model.supports_structured_output:
      schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
      response = await self._model.generate_structured(prompt_text, schema)
      self._record_usage(agent=self.name, purpose="plan_lesson", call_index="1/1", usage=response.usage)
      plan_json = response.content
    else:
      # prompt_parts = [
      #   prompt_text,
      #   format_schema_block(schema, label="JSON SCHEMA (Lesson Plan)"),
      #   "Output ONLY valid JSON.",
      # ]
      #
      # prompt_with_schema = "\n\n".join(prompt_parts)
      # raw = await self._model.generate(prompt_with_schema)
      
      raw = await self._model.generate(prompt_text)
      self._record_usage(agent=self.name, purpose="plan_lesson", call_index="1/1", usage=raw.usage)
      
      try:
        cleaned = self._model.strip_json_fences(raw.content)
        plan_json = cast(dict[str, Any], json.loads(cleaned))
      except json.JSONDecodeError as exc:
        logger.error("Planner failed to parse JSON: %s", exc)
        raise RuntimeError(f"Failed to parse planner JSON: {exc}") from exc

    try:
      plan = LessonPlan.model_validate(plan_json)
      logger.debug("Planner returned valid JSON")
    except ValidationError as exc:
      logger.error("Planner returned invalid JSON: %s", exc)
      logger.info("Attempting to repair the json")
      plan_json = _repair_planner_json(plan_json)
      plan = LessonPlan.model_validate(plan_json)
      logger.info("Repair succeeded")
    
    if len(plan.sections) != input_data.section_count:
      message = f"Planner returned {len(plan.sections)} sections; expected {input_data.section_count}."
      logger.error(message)
      raise RuntimeError(message)
    
    return plan
