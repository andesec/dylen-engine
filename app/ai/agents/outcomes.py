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
  template = _load_prompt("outcomes_agent_improved.md")
  teaching_style = ", ".join(input_data.teaching_style)
  secondary_language = _normalize_optional_text(input_data.secondary_language)

  rendered = template
  rendered = rendered.replace("{{TOPIC}}", input_data.topic)
  rendered = rendered.replace("{{DETAILS}}", input_data.details)
  rendered = rendered.replace("{{LEARNING_FOCUS}}", input_data.learning_focus)
  rendered = rendered.replace("{{LEARNER_LEVEL}}", input_data.learner_level)
  rendered = rendered.replace("{{TEACHING_STYLE}}", teaching_style)
  rendered = rendered.replace("{{SECTION_COUNT}}", str(int(input_data.section_count)))
  rendered = rendered.replace("{{PRIMARY_LANGUAGE}}", input_data.lesson_language)
  rendered = rendered.replace("{{SECONDARY_LANGUAGE}}", secondary_language)
  return rendered


class OutcomesAgent(BaseAgent[OutcomesAgentInput, OutcomesAgentResponse]):
  """Generate a small list of learning outcomes or block disallowed topics."""

  name = "Outcomes"

  async def run(self, input_data: OutcomesAgentInput, ctx: JobContext) -> OutcomesAgentResponse:
    """Generate outcomes with structured output when supported."""
    try:
      dummy_json = self._load_dummy_json()

      if dummy_json is not None:
        logger.info("Using deterministic dummy output for Outcomes")
        return OutcomesAgentResponse.model_validate(dummy_json)

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

      return payload
    except Exception as exc:  # noqa: BLE001
      logger.error("Outcomes agent failed unexpectedly.", exc_info=True)
      return OutcomesAgentResponse(ok=False, error="TOPIC_NOT_ALLOWED", message=f"Outcomes generation failed: {exc}", blocked_category="invalid_input", outcomes=[])
