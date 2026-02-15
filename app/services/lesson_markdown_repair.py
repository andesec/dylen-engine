"""Overlong Markdown repair helpers.

Why:
  - Markdown widgets can contain arbitrarily large strings, which can cause DoS risk and
    exceed storage/render budgets.
  - When a hidden, per-user repair flag is enabled, the backend should refactor content
    via the existing Repairer agent to fit within a hard character limit.

How:
  - Detect overlong MarkdownText widgets using deterministic traversal utilities.
  - Repair sections one-by-one by invoking the Repairer agent with targeted error paths.
  - Re-check the hard limit after each repair round and stop once compliant.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from app.ai.agents.repairer import RepairerAgent
from app.ai.pipeline.contracts import GenerationRequest, JobContext, RepairInput, SectionDraft, StructuredSection
from app.ai.router import get_model_for_mode
from app.config import Settings
from app.schema.markdown_limits import collect_overlong_markdown_errors, collect_overlong_markdown_errors_by_section
from app.schema.service import SchemaService
from app.services.runtime_config import get_repair_model

MAX_MARKDOWN_REPAIR_ROUNDS = 2


async def repair_lesson_overlong_markdown(lesson_json: dict[str, Any], *, topic: str, settings: Settings, max_markdown_chars: int, job_id: str, runtime_config: dict[str, Any] | None = None) -> dict[str, Any]:
  """Repair MarkdownText widgets that exceed the configured hard limit.

  Why:
    - This is intentionally section-scoped to match how the Repairer agent operates in the pipeline.
    - A bounded retry loop prevents runaway repair costs and keeps behavior deterministic.
  """
  if max_markdown_chars <= 0:
    raise ValueError("max_markdown_chars must be positive.")
  repaired = deepcopy(lesson_json)
  blocks = repaired.get("blocks")
  if not isinstance(blocks, list) or not blocks:
    return repaired
  errors_by_section = collect_overlong_markdown_errors_by_section(repaired, max_markdown_chars=max_markdown_chars)
  if not errors_by_section:
    return repaired
  # Build a Repairer agent with the configured provider/model so behavior matches pipeline repair.
  runtime_config = runtime_config or {}
  provider, model_name = get_repair_model(runtime_config)
  model_instance = get_model_for_mode(provider, model_name, agent="repairer")
  schema_service = SchemaService()
  agent = RepairerAgent(model=model_instance, prov=provider, schema=schema_service)
  request = GenerationRequest(topic=topic, section_count=max(1, len(blocks)))
  metadata = {"limits.max_markdown_chars": max_markdown_chars}
  ctx = JobContext(job_id=job_id, created_at=datetime.utcnow(), provider=provider, model=str(model_name or ""), request=request, metadata=metadata)
  # Repair only the sections that are currently violating the hard limit.
  for section_number in sorted(errors_by_section.keys()):
    index = section_number - 1
    if index < 0 or index >= len(blocks):
      continue
    section_payload = blocks[index]
    if not isinstance(section_payload, dict):
      continue
    section_title = str(section_payload.get("section") or f"Section {section_number}")
    errors = errors_by_section[section_number]
    # Attempt bounded repair rounds, re-checking the hard limit each time.
    for _round in range(MAX_MARKDOWN_REPAIR_ROUNDS):
      repair_input = RepairInput(section=SectionDraft(section_number=section_number, title=section_title, raw_text=""), structured=StructuredSection(section_number=section_number, payload=section_payload, validation_errors=errors))
      result = await agent.run(repair_input, ctx)
      section_payload = result.fixed_json
      blocks[index] = section_payload
      wrapper = {"title": topic, "blocks": [section_payload]}
      errors = collect_overlong_markdown_errors(wrapper, max_markdown_chars=max_markdown_chars)
      if not errors:
        break
    if errors:
      raise ValueError(f"Markdown repair did not converge for section {section_number}.")
  return repaired
