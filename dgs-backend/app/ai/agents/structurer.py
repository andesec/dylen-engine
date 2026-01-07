"""Structurer agent implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import format_schema_block, render_structurer_prompt
from app.ai.pipeline.contracts import JobContext, SectionDraft, StructuredSection


class StructurerAgent(BaseAgent[SectionDraft, StructuredSection]):
  """Convert a raw section draft into structured JSON."""

  name = "Structurer"

  async def run(self, input_data: SectionDraft, ctx: JobContext) -> StructuredSection:
    """Structure a section draft into JSON."""
    logger = logging.getLogger(__name__)
    request = ctx.request
    dummy_json = self._load_dummy_json()
    if dummy_json is not None:
      # Use deterministic fixture output when configured to avoid provider calls.
      section_index = input_data.section_number
      topic = request.topic
      validator = self._schema_service.validate_section_payload
      ok, errors, _ = validator(dummy_json, topic=topic, section_index=section_index)
      validation_errors = [] if ok else errors
      return StructuredSection(section_number=section_index, payload=dummy_json, validation_errors=validation_errors)
    schema_version = str((ctx.metadata or {}).get("schema_version", ""))
    structured_output = bool((ctx.metadata or {}).get("structured_output", True))
    prompt_text = render_structurer_prompt(request, input_data, schema_version)
    schema = self._schema_service.section_schema()
    if self._model.supports_structured_output and structured_output:
      schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
      response = await self._model.generate_structured(prompt_text, schema)
      purpose = f"struct_section_{input_data.section_number}_of_{request.depth}"
      call_index = f"{input_data.section_number}/{request.depth}"
      self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=response.usage)
      section_json = response.content
    else:
      prompt_parts = [
        prompt_text,
        format_schema_block(schema, label="JSON SCHEMA (Section)"),
        "Output ONLY valid JSON.",
      ]
      prompt_with_schema = "\n\n".join(prompt_parts)
      raw = await self._model.generate(prompt_with_schema)
      purpose = f"struct_section_{input_data.section_number}_of_{request.depth}"
      call_index = f"{input_data.section_number}/{request.depth}"
      self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=raw.usage)
      try:
        cleaned = self._model.strip_json_fences(raw.content)
        section_json = cast(dict[str, Any], json.loads(cleaned))
      except json.JSONDecodeError as exc:
        logger.error("Structurer failed to parse JSON: %s", exc)
        raise RuntimeError(f"Failed to parse section JSON: {exc}") from exc

    section_index = input_data.section_number
    topic = request.topic
    validator = self._schema_service.validate_section_payload
    ok, errors, _ = validator(section_json, topic=topic, section_index=section_index)
    validation_errors = [] if ok else errors
    return StructuredSection(section_number=section_index, payload=section_json, validation_errors=validation_errors)
