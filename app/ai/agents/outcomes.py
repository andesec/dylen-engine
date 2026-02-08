"""Outcomes agent implementation."""

from __future__ import annotations

import logging
from typing import Any, cast

from pydantic import ValidationError

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import _load_prompt
from app.ai.errors import is_output_error
from app.ai.pipeline.contracts import JobContext
from app.schema.outcomes import OutcomesAgentInput, OutcomesAgentResponse
from app.telemetry.context import llm_call_context

logger = logging.getLogger(__name__)


def _normalize_optional_text(value: str | None) -> str:
  """Normalize optional request fields for prompt rendering."""
  if value is None or value.strip() == "":
    return "-"
  return value.strip()


def _render_prompt(input_data: OutcomesAgentInput) -> str:
  """Render the outcomes prompt with concrete request inputs."""
  template = _load_prompt("outcomes_agent.md")
  widgets = ", ".join(input_data.widgets) if input_data.widgets else "-"
  teaching_style = ", ".join(input_data.teaching_style) if input_data.teaching_style else "-"
  blueprint = _normalize_optional_text(input_data.blueprint)
  learner_level = _normalize_optional_text(input_data.learner_level)
  rendered = template
  rendered = rendered.replace("{{TOPIC}}", _normalize_optional_text(input_data.topic))
  rendered = rendered.replace("{{DETAILS}}", _normalize_optional_text(input_data.details))
  rendered = rendered.replace("{{LEARNER_LEVEL}}", learner_level)
  rendered = rendered.replace("{{TEACHING_STYLE}}", teaching_style)
  rendered = rendered.replace("{{BLUEPRINT}}", blueprint)
  rendered = rendered.replace("{{DEPTH}}", _normalize_optional_text(input_data.depth))
  rendered = rendered.replace("{{PRIMARY_LANGUAGE}}", _normalize_optional_text(input_data.primary_language))
  rendered = rendered.replace("{{WIDGETS}}", widgets)
  rendered = rendered.replace("{{MAX_OUTCOMES}}", str(int(input_data.max_outcomes)))
  return rendered


class OutcomesAgent(BaseAgent[OutcomesAgentInput, OutcomesAgentResponse]):
  """Generate a small list of learning outcomes or block disallowed topics."""

  name = "Outcomes"

  async def run(self, input_data: OutcomesAgentInput, ctx: JobContext) -> OutcomesAgentResponse:
    """Generate outcomes with structured output when supported."""
    dummy_json = self._load_dummy_json()

    if dummy_json is not None:
      logger.info("Using deterministic dummy output for Outcomes")
      payload = OutcomesAgentResponse.model_validate(dummy_json)
      return self._enforce_max_outcomes(payload, max_outcomes=int(input_data.max_outcomes))

    prompt_text = _render_prompt(input_data)
    schema = OutcomesAgentResponse.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")

    schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
    with llm_call_context(agent=self.name, lesson_topic=input_data.topic, job_id=ctx.job_id, purpose="outcomes_check", call_index="1/1"):
      try:
        response = await self._model.generate_structured(prompt_text, schema)
      except Exception as exc:  # noqa: BLE001
        if is_output_error(exc):
          logger.error(f"Outcomes agent failed to generate JSON: {exc}")
        raise

    self._record_usage(agent=self.name, purpose="outcomes_check", call_index="1/1", usage=response.usage)
    result_json = cast(dict[str, Any], response.content)

    try:
      payload = OutcomesAgentResponse.model_validate(result_json)
    except ValidationError as exc:
      logger.error("Outcomes agent returned invalid JSON: %s", exc)
      raise RuntimeError(f"Outcomes agent returned invalid JSON: {exc}") from exc

    return self._enforce_max_outcomes(payload, max_outcomes=int(input_data.max_outcomes))

  def _enforce_max_outcomes(self, payload: OutcomesAgentResponse, *, max_outcomes: int) -> OutcomesAgentResponse:
    """Clamp outcomes to the configured maximum to prevent oversized responses."""
    # Clamp only the allowed path; blocked responses must remain empty by schema contract.
    if payload.ok and len(payload.outcomes) > max_outcomes:
      trimmed = payload.model_copy()
      trimmed.outcomes = list(trimmed.outcomes)[:max_outcomes]
      return trimmed
    return payload
