"""Planner agent implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from pydantic import ValidationError

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import render_planner_prompt
from app.ai.errors import is_output_error
from app.ai.json_parser import parse_json_with_fallback
from app.ai.pipeline.contracts import GenerationRequest, JobContext, LessonPlan
from app.telemetry.context import llm_call_context


def _repair_planner_json(plan_json: dict[str, Any]) -> dict[str, Any]:
  """Repair JSON by converting between strings and lists of strings."""

  if "sections" in plan_json:
    # Normalize list/string mismatches inside each section payload.

    for section in plan_json["sections"]:
      # Convert string to list for fields that should be lists

      for field in ["data_collection_points"]:
        if field in section and isinstance(section[field], str):
          section[field] = [section[field]]

      # Convert array to string for fields that should be strings.

      for field in ["data_collection_points", "continuity_note"]:
        for _k, v in section[field]:
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

    # Prefer deterministic fixtures during local/test runs.
    dummy_json = self._load_dummy_json()

    if dummy_json is not None:
      logger.info("Using deterministic dummy output for Planner")
      # Use deterministic fixture output when configured to avoid provider calls.
      plan = LessonPlan.model_validate(dummy_json)
      return plan

    # Build the prompt and schema to request a structured plan.
    prompt_text = render_planner_prompt(input_data)
    schema = LessonPlan.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")

    if self._model.supports_structured_output:
      schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
      # Stamp the provider call with agent context for audit logging.
      with llm_call_context(agent=self.name, lesson_topic=input_data.topic, job_id=ctx.job_id, purpose="plan_lesson", call_index="1/1"):
        try:
          response = await self._model.generate_structured(prompt_text, schema)
        except Exception as exc:  # noqa: BLE001
          if not is_output_error(exc):
            raise
          # Retry the same request with the parser error appended.
          retry_prompt = self._build_json_retry_prompt(prompt_text=prompt_text, error=exc)
          retry_purpose = "plan_lesson_retry"
          retry_call_index = "retry/1"

          with llm_call_context(agent=self.name, lesson_topic=input_data.topic, job_id=ctx.job_id, purpose=retry_purpose, call_index=retry_call_index):
            response = await self._model.generate_structured(retry_prompt, schema)

          self._record_usage(agent=self.name, purpose=retry_purpose, call_index=retry_call_index, usage=response.usage)

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

      # Stamp the provider call with agent context for audit logging.
      with llm_call_context(agent=self.name, lesson_topic=input_data.topic, job_id=ctx.job_id, purpose="plan_lesson", call_index="1/1"):
        raw = await self._model.generate(prompt_text)

      self._record_usage(agent=self.name, purpose="plan_lesson", call_index="1/1", usage=raw.usage)

      # Parse the model output with a lenient fallback to reduce retry churn.

      try:
        cleaned = self._model.strip_json_fences(raw.content)
        plan_json = cast(dict[str, Any], parse_json_with_fallback(cleaned))
      except json.JSONDecodeError as exc:
        logger.error("Planner failed to parse JSON: %s", exc)
        # Retry the same request with the parser error appended.
        retry_prompt = self._build_json_retry_prompt(prompt_text=prompt_text, error=exc)
        retry_purpose = "plan_lesson_retry"
        retry_call_index = "retry/1"

        with llm_call_context(agent=self.name, lesson_topic=input_data.topic, job_id=ctx.job_id, purpose=retry_purpose, call_index=retry_call_index):
          retry_raw = await self._model.generate(retry_prompt)

        self._record_usage(agent=self.name, purpose=retry_purpose, call_index=retry_call_index, usage=retry_raw.usage)

        try:
          cleaned_retry = self._model.strip_json_fences(retry_raw.content)
          plan_json = cast(dict[str, Any], parse_json_with_fallback(cleaned_retry))
        except json.JSONDecodeError as retry_exc:
          logger.error("Planner retry failed to parse JSON: %s", retry_exc)
          raise RuntimeError(f"Failed to parse planner JSON after retry: {retry_exc}") from retry_exc

    try:
      plan = LessonPlan.model_validate(plan_json)
      logger.debug("Planner returned valid JSON")

    except ValidationError as exc:
      logger.error("Planner returned invalid JSON: %s", exc)
      logger.info("Attempting to repair the json")
      plan_json = _repair_planner_json(plan_json)
      plan = LessonPlan.model_validate(plan_json)
      logger.info("Repair succeeded")

    # Ensure we respect depth rules from the caller.
    if len(plan.sections) != input_data.section_count:
      message = f"Planner returned {len(plan.sections)} sections; expected {input_data.section_count}."
      logger.error(message)
      raise RuntimeError(message)

    return plan
