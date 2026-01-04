"""Repairer agent implementation."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import format_schema_block, render_repair_prompt
from app.ai.deterministic_repair import attempt_deterministic_repair
from app.ai.pipeline.contracts import JobContext, RepairInput, RepairResult

JsonDict = dict[str, Any]
Errors = list[str]


class RepairerAgent(BaseAgent[RepairInput, RepairResult]):
  """Repair invalid JSON sections."""

  name = "Repairer"

  async def run(self, input_data: RepairInput, ctx: JobContext) -> RepairResult:
    """Repair a structured section when validation fails."""
    logger = logging.getLogger(__name__)
    request = ctx.request
    section = input_data.section
    structured = input_data.structured
    errors = structured.validation_errors
    section_json: JsonDict = structured.payload
    topic = request.topic
    section_number = section.section_number
    dummy_json = self._load_dummy_json()
    if dummy_json is not None:
      # Use deterministic fixture output when configured to avoid provider calls.
      validator = self._schema_service.validate_section_payload
      ok, repaired_errors, _ = validator(dummy_json, topic=topic, section_index=section_number)
      err_list = [] if ok else repaired_errors
      return RepairResult(section_number=section_number, fixed_json=dummy_json, changes=["dummy_fixture"], errors=err_list)

    if errors:
      section_json = self._deterministic_repair(section_json, errors, topic, section_number)
      validator = self._schema_service.validate_section_payload
      ok, errors, _ = validator(section_json, topic=topic, section_index=section_number)
      if ok:
        changes = ["deterministic_repair"]
        return RepairResult(section_number=section_number, fixed_json=section_json, changes=changes, errors=[])

    if not errors:
      return RepairResult(section_number=section_number, fixed_json=section_json, changes=[], errors=[])

    prompt_text = render_repair_prompt(request, section, section_json, errors)
    schema = self._schema_service.section_schema()
    if self._model.supports_structured_output:
      schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
      response = await self._model.generate_structured(prompt_text, schema)
      purpose = f"repair_section_{section.section_number}_of_{request.depth}"
      call_index = f"{section.section_number}/{request.depth}"
      self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=response.usage)
      repaired_json = response.content
    else:
      prompt_parts = [
        prompt_text,
        format_schema_block(schema, label="JSON SCHEMA (Section)"),
        "Output ONLY valid JSON.",
      ]
      prompt_with_schema = "\n\n".join(prompt_parts)
      raw = await self._model.generate(prompt_with_schema)
      purpose = f"repair_section_{section.section_number}_of_{request.depth}"
      call_index = f"{section.section_number}/{request.depth}"
      self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=raw.usage)
      try:
        cleaned = self._model.strip_json_fences(raw.content)
        repaired_json = cast(dict[str, Any], json.loads(cleaned))
      except json.JSONDecodeError as exc:
        logger.error("Repairer failed to parse JSON: %s", exc)
        raise RuntimeError(f"Failed to parse repaired section JSON: {exc}") from exc

    validator = self._schema_service.validate_section_payload
    ok, repaired_errors, _ = validator(repaired_json, topic=topic, section_index=section_number)
    changes = ["ai_repair"]
    err_list = [] if ok else repaired_errors
    return RepairResult(section_number=section_number, fixed_json=repaired_json, changes=changes, errors=err_list)

  @staticmethod
  def _deterministic_repair(section_json: JsonDict, errors: Errors, topic: str, section_number: int) -> JsonDict:
    payload = {"title": f"{topic} - Section {section_number}", "blocks": [section_json]}
    repaired = attempt_deterministic_repair(payload, errors)
    blocks = repaired.get("blocks")
    if isinstance(blocks, list) and blocks:
      first_block = blocks[0]
      if isinstance(first_block, dict):
        return first_block
    return section_json
