"""Merged gatherer + structurer agent implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import render_gatherer_structurer_prompt
from app.ai.errors import is_output_error
from app.ai.json_parser import parse_json_with_fallback
from app.ai.pipeline.contracts import JobContext, PlanSection, StructuredSection
from app.telemetry.context import llm_call_context


class GathererStructurerAgent(BaseAgent[PlanSection, StructuredSection]):
  """Collect and structure a planned section in a single call."""

  name = "GathererStructurer"

  async def run(self, input_data: PlanSection, ctx: JobContext) -> StructuredSection:
    """Generate a structured section directly from the planner output."""
    logger = logging.getLogger(__name__)
    request = ctx.request

    # Prefer deterministic fixture output during local/test runs.
    dummy_json = self._load_dummy_json()

    if dummy_json is not None:
      section_index = input_data.section_number
      topic = request.topic
      validator = self._schema_service.validate_section_payload
      ok, errors, _ = validator(dummy_json, topic=topic, section_index=section_index)
      validation_errors = [] if ok else errors
      return StructuredSection(section_number=section_index, payload=dummy_json, validation_errors=validation_errors)

    schema_version = str((ctx.metadata or {}).get("schema_version", ""))
    structured_output = bool((ctx.metadata or {}).get("structured_output", True))
    prompt_text = render_gatherer_structurer_prompt(request, input_data, schema_version)
    schema = self._schema_service.section_schema()
    purpose = f"gather_struct_section_{input_data.section_number}_of_{request.depth}"
    call_index = f"{input_data.section_number}/{request.depth}"

    # Apply context to correlate provider calls with the agent and lesson topic.
    with llm_call_context(
      agent=self.name, lesson_topic=request.topic, job_id=ctx.job_id, purpose=purpose, call_index=call_index
    ):
      if self._model.supports_structured_output and structured_output:
        schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
        try:
          response = await self._model.generate_structured(prompt_text, schema)
        except Exception as exc:  # noqa: BLE001
          if not is_output_error(exc):
            raise
          # Retry the same request with the parser error appended.
          retry_prompt = self._build_json_retry_prompt(prompt_text=prompt_text, error=exc)
          retry_purpose = f"gather_struct_section_retry_{input_data.section_number}_of_{request.depth}"
          retry_call_index = f"retry/{input_data.section_number}/{request.depth}"

          with llm_call_context(
            agent=self.name,
            lesson_topic=request.topic,
            job_id=ctx.job_id,
            purpose=retry_purpose,
            call_index=retry_call_index,
          ):
            response = await self._model.generate_structured(retry_prompt, schema)

          self._record_usage(agent=self.name, purpose=retry_purpose, call_index=retry_call_index, usage=response.usage)

        self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=response.usage)
        section_json = response.content
      else:
        raw = await self._model.generate(prompt_text)
        self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=raw.usage)

        # Parse the model output with a lenient fallback to reduce retry churn.

        try:
          cleaned = self._model.strip_json_fences(raw.content)
          section_json = cast(dict[str, Any], parse_json_with_fallback(cleaned))
        except json.JSONDecodeError as exc:
          logger.error("Merged gatherer-structurer failed to parse JSON: %s", exc)
          # Retry the same request with the parser error appended.
          retry_prompt = self._build_json_retry_prompt(prompt_text=prompt_text, error=exc)
          retry_purpose = f"gather_struct_section_retry_{input_data.section_number}_of_{request.depth}"
          retry_call_index = f"retry/{input_data.section_number}/{request.depth}"

          with llm_call_context(
            agent=self.name,
            lesson_topic=request.topic,
            job_id=ctx.job_id,
            purpose=retry_purpose,
            call_index=retry_call_index,
          ):
            retry_raw = await self._model.generate(retry_prompt)

          self._record_usage(agent=self.name, purpose=retry_purpose, call_index=retry_call_index, usage=retry_raw.usage)

          try:
            cleaned_retry = self._model.strip_json_fences(retry_raw.content)
            section_json = cast(dict[str, Any], parse_json_with_fallback(cleaned_retry))
          except json.JSONDecodeError as retry_exc:
            logger.error("Merged gatherer-structurer retry failed to parse JSON: %s", retry_exc)
            raise RuntimeError(f"Failed to parse merged section JSON after retry: {retry_exc}") from retry_exc

    section_index = input_data.section_number
    topic = request.topic

    # Validate the structured section against the schema.
    validator = self._schema_service.validate_section_payload
    ok, errors, _ = validator(section_json, topic=topic, section_index=section_index)
    validation_errors = [] if ok else errors
    return StructuredSection(section_number=section_index, payload=section_json, validation_errors=validation_errors)
