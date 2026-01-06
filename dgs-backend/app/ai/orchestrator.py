"""Orchestration for the multi-agent AI pipeline."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, cast

from app.ai.agents import GathererAgent, PlannerAgent, RepairerAgent, StructurerAgent, StitcherAgent
from app.ai.pipeline.contracts import (
  GenerationRequest,
  JobContext,
  RepairInput,
  SectionDraft,
  StructuredSection,
  StructuredSectionBatch,
)
from app.ai.providers.base import AIModel
from app.ai.router import get_model_for_mode
from app.schema.service import SchemaService

OptStr = str | None
Msgs = list[str] | None
ProgressCallback = Callable[[str, OptStr, Msgs, bool], None] | None


@dataclass(frozen=True)
class OrchestrationResult:
  """Output from the AI orchestration layer."""

  lesson_json: dict[str, Any]
  provider_a: str
  model_a: str
  provider_b: str
  model_b: str
  validation_errors: list[str] | None = None
  logs: list[str] = field(default_factory=list)
  usage: list[dict[str, Any]] = field(default_factory=list)
  total_cost: float = 0.0
  artifacts: dict[str, Any] | None = None


class DgsOrchestrator:
  """Coordinates the gatherer and structurer agents."""

  def __init__(
    self,
    *,
    gatherer_provider: str,
    gatherer_model: str | None,
    planner_provider: str | None,
    planner_model: str | None,
    structurer_provider: str,
    structurer_model: str | None,
    repair_provider: str,
    repair_model: str | None,
    schema_version: str,
  ) -> None:
    self._gatherer_provider = gatherer_provider
    self._gatherer_model_name = gatherer_model
    self._planner_provider = planner_provider or structurer_provider
    self._planner_model_name = planner_model
    self._structurer_provider = structurer_provider
    self._structurer_model_name = structurer_model
    self._repair_provider = repair_provider
    self._repair_model_name = repair_model
    self._schema_version = schema_version
    self._schema_service = SchemaService()

  async def generate_lesson(
    self,
    *,
    topic: str,
    details: str | None = None,
    blueprint: str | None = None,
    teaching_style: str | None = None,
    learner_level: str | None = None,
    depth: str | None = None,
    schema_version: str | None = None,
    structurer_model: str | None = None,
    gatherer_model: str | None = None,
    structured_output: bool = True,
    language: str | None = None,
    enable_repair: bool = True,
    progress_callback: ProgressCallback = None,
  ) -> OrchestrationResult:
    """Run the 5-agent pipeline and return lesson JSON."""
    logger = logging.getLogger(__name__)
    logs: list[str] = []
    all_usage: list[dict[str, Any]] = []
    validation_errors: list[str] | None = None

    def _report_progress(phase_name: str, subphase: OptStr, messages: Msgs = None, advance: bool = True) -> None:
      if progress_callback:
        progress_callback(phase_name, subphase, messages, advance)

    gatherer_model_name = gatherer_model or self._gatherer_model_name
    structurer_model_name = structurer_model or self._structurer_model_name
    planner_model_name = self._planner_model_name or structurer_model_name

    topic_preview = topic[:50] + "..." if len(topic) >= 50 else topic
    log_msg = f"Starting generation for topic: '{topic_preview}'"
    logs.append(log_msg)
    logger.info(log_msg)

    log_msg = f"Gatherer: {self._gatherer_provider}/{gatherer_model_name or 'default'}"
    logs.append(log_msg)
    logger.info(log_msg)

    log_msg = f"Planner: {self._planner_provider}/{planner_model_name or 'default'}"
    logs.append(log_msg)
    logger.info(log_msg)

    log_msg = f"Structurer: {self._structurer_provider}/{structurer_model_name or 'default'}"
    logs.append(log_msg)
    logger.info(log_msg)

    depth = _coerce_depth(depth)

    lang = language
    request = GenerationRequest(
      topic=topic,
      prompt=details,
      depth=depth,
      blueprint=blueprint,
      teaching_style=teaching_style,
      learner_level=learner_level,
      language=lang,
      constraints=None,
    )
    created_at = datetime.utcnow()
    schema_ver = schema_version or self._schema_version
    meta = {"schema_version": schema_ver, "structured_output": structured_output}
    jid = "unknown"
    prov = "multi"
    mod = "multi"
    ctx = JobContext(job_id=jid, created_at=created_at, provider=prov, model=mod, request=request, metadata=meta)
    usage_sink = all_usage.append

    gatherer_model_instance = get_model_for_mode(self._gatherer_provider, gatherer_model_name)
    planner_model_instance = get_model_for_mode(self._planner_provider, planner_model_name)
    structurer_model_instance = get_model_for_mode(self._structurer_provider, structurer_model_name)
    repairer_model_instance = get_model_for_mode(self._repair_provider, self._repair_model_name)

    schema = self._schema_service
    use = usage_sink
    gatherer_prov = self._gatherer_provider
    planner_prov = self._planner_provider
    structurer_prov = self._structurer_provider
    repair_prov = self._repair_provider
    planner_agent = PlannerAgent(model=planner_model_instance, prov=planner_prov, schema=schema, use=use)
    gatherer_agent = GathererAgent(model=gatherer_model_instance, prov=gatherer_prov, schema=schema, use=use)
    structurer_agent = StructurerAgent(model=structurer_model_instance, prov=structurer_prov, schema=schema, use=use)
    repairer_agent = RepairerAgent(model=repairer_model_instance, prov=repair_prov, schema=schema, use=use)
    stitcher_agent = StitcherAgent(model=structurer_model_instance, prov=structurer_prov, schema=schema, use=use)

    _report_progress("plan", "planner_start", ["Planning lesson sections..."])
    try:
      lesson_plan = await planner_agent.run(request, ctx)
    except Exception as exc:
      planner_model = _model_name(planner_model_instance)
      _log_request_failure(logger=logger, logs=logs, agent="Planner", provider=planner_prov, model=planner_model, prompt=None, response=None, error=exc)
      raise
    _report_progress("plan", "planner_complete", ["Lesson plan ready."])

    sections: dict[int, SectionDraft] = {}
    draft_artifacts: list[dict[str, Any]] = []
    structured_artifacts: list[dict[str, Any]] = []
    repair_artifacts: list[dict[str, Any]] = []
    for plan_section in lesson_plan.sections:
      section_index = plan_section.section_number
      gather_subphase = f"gather_section_{section_index}_of_{depth}"
      gather_msg = f"Gathering section {section_index}/{depth}: {plan_section.title}"
      _report_progress("collect", gather_subphase, [gather_msg])
      try:
        draft = await gatherer_agent.run(plan_section, ctx)
      except Exception as exc:
        gather_model = _model_name(gatherer_model_instance)
        _log_request_failure(logger=logger, logs=logs, agent="Gatherer", provider=gatherer_prov, model=gather_model, prompt=None, response=None, error=exc)
        logs.append(f"Gatherer failed section {section_index}/{depth}.")
        continue
      if section_index < 1 or section_index > depth:
        logs.append(f"Skipping out-of-range section {section_index}.")
        continue
      sections[section_index] = draft
      draft_artifacts.append(draft.model_dump(mode="python"))
      extract_subphase = f"extract_section_{section_index}_of_{depth}"
      extract_msg = f"Extracted section {section_index}/{depth}"
      _report_progress("collect", extract_subphase, [extract_msg])

    # Ensure we collected all requested sections before structuring.
    if len(sections) < depth:
      missing = sorted(set(range(1, depth + 1)) - set(sections.keys()))
      logs.append(f"Missing extracted sections: {missing}")
      logger.warning("Missing extracted sections: %s", missing)

    structured_sections: list[StructuredSection] = []
    if not enable_repair:
      logs.append("Repair is disabled; failed sections are skipped.")
      logger.info("Repair is disabled; failed sections are skipped.")

    for section_index in range(1, depth + 1):
      draft = sections.get(section_index)
      if draft is None:
        logs.append(f"Skipping missing section {section_index}.")
        logger.warning("Skipping missing section %s.", section_index)
        continue

      struct_subphase = f"struct_section_{section_index}_of_{depth}"
      struct_msg = f"Structuring section {section_index}/{depth}: {draft.title}"
      _report_progress("transform", struct_subphase, [struct_msg])

      try:
        structured = await structurer_agent.run(draft, ctx)
      except RuntimeError as exc:
        structurer_model = _model_name(structurer_model_instance)
        _log_request_failure(logger=logger, logs=logs, agent="Structurer", provider=self._structurer_provider, model=structurer_model, prompt=None, response=None, error=exc)
        logs.append(f"Skipping section {section_index} due to structurer failure.")
        continue

      structured_artifacts.append(structured.model_dump(mode="python"))
      if structured.validation_errors and not enable_repair:
        validation_errors = structured.validation_errors
        logs.append(f"Section {section_index} failed validation: {structured.validation_errors}")
        logger.error("Section %s failed validation: %s", section_index, structured.validation_errors)
        continue

      section_json = structured.payload
      if enable_repair:
        repair_input = RepairInput(section=draft, structured=structured)
        try:
          repair_result = await repairer_agent.run(repair_input, ctx)
        except RuntimeError as exc:
          repair_model = _model_name(repairer_model_instance)
          _log_request_failure(logger=logger, logs=logs, agent="Repairer", provider=self._repair_provider, model=repair_model, prompt=None, response=None, error=exc)
          logs.append(f"Skipping section {section_index} due to repair failure.")
          continue
        repair_artifacts.append(repair_result.model_dump(mode="python"))
        if repair_result.errors:
          validation_errors = repair_result.errors
          logs.append(f"Section {section_index} failed repair validation: {repair_result.errors}")
          logger.error("Section %s failed repair validation: %s", section_index, repair_result.errors)
          continue
        section_json = repair_result.fixed_json

      validate_subphase = f"validate_section_{section_index}_of_{depth}"
      _report_progress("transform", validate_subphase, [f"Section {section_index} validated."])
      structured_section = StructuredSection(section_number=section_index, json=section_json, validation_errors=[])
      structured_sections.append(structured_section)

    _report_progress("transform", "stitch_sections", ["Stitching sections..."])
    batch = StructuredSectionBatch(sections=structured_sections)
    stitch_result = await stitcher_agent.run(batch, ctx)
    lesson_json = stitch_result.lesson_json
    metadata = stitch_result.metadata or {}
    validation_errors = metadata.get("validation_errors") or None

    log_msg = "Generation pipeline complete"
    logs.append(log_msg)
    logger.info(log_msg)

    total_cost = self._calculate_total_cost(all_usage)

    artifacts = {
      "plan": lesson_plan.model_dump(mode="python"),
      "drafts": draft_artifacts,
      "structured_sections": structured_artifacts,
      "repairs": repair_artifacts,
      "final_lesson": lesson_json,
    }
    gatherer_model = _model_name(gatherer_model_instance)
    structurer_model = _model_name(structurer_model_instance)
    validation = validation_errors if validation_errors else None
    return OrchestrationResult(lesson_json=lesson_json, provider_a=self._gatherer_provider, model_a=gatherer_model, provider_b=self._structurer_provider, model_b=structurer_model, validation_errors=validation, logs=logs, usage=all_usage, total_cost=total_cost, artifacts=artifacts)

  def _calculate_total_cost(self, usage: list[dict[str, Any]]) -> float:
    """Estimate total cost based on token usage."""
    # Price table can be overridden via MODEL_PRICING_JSON.
    pricing = _load_pricing_table()

    total = 0.0
    for entry in usage:
      model = entry.get("model", "")
      price_in, price_out = pricing.get(model, (0.5, 1.5))

      in_tokens = int(entry.get("prompt_tokens") or 0)
      out_tokens = int(entry.get("completion_tokens") or 0)

      call_cost = (in_tokens / 1_000_000) * price_in
      call_cost += (out_tokens / 1_000_000) * price_out

      entry["input_tokens"] = in_tokens
      entry["output_tokens"] = out_tokens
      entry["estimated_cost"] = round(call_cost, 6)

      total += call_cost

    return round(total, 6)

def _log_request_failure(
  *,
  logger: logging.Logger,
  logs: list[str] | None,
  agent: str,
  provider: str,
  model: str,
  prompt: str | None,
  response: str | None,
  error: Exception,
) -> None:
  """Log request failures with prompt/response details."""
  message = f"{agent} request failed (provider={provider}, model={model}): {error}"
  if logs is not None:
    logs.append(message)
  logger.error(message)
  if prompt:
    logger.error("%s prompt:\n%s", agent, prompt)
  else:
    logger.error("%s prompt: <none>", agent)
  if response is None:
    logger.error("%s response: <none>", agent)
  else:
    logger.error("%s response:\n%s", agent, response)


def _model_name(model: AIModel) -> str:
  return getattr(model, "name", "unknown")


@lru_cache(maxsize=1)
def _load_pricing_table() -> dict[str, tuple[float, float]]:
  default_prices = {
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.075, 0.30),
    "gemini-2.0-flash-exp": (0.0, 0.0),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 5.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (5.0, 15.0),
    "anthropic/claude-3.5-sonnet": (3.0, 15.0),
  }
  raw = os.getenv("MODEL_PRICING_JSON")
  if not raw:
    return default_prices
  try:
    parsed = json.loads(raw)
  except json.JSONDecodeError:
    return default_prices

  if not isinstance(parsed, dict):
    return default_prices

  prices = dict(default_prices)
  for model, value in parsed.items():
    if not isinstance(value, dict):
      continue
    price_in = value.get("input")
    price_out = value.get("output")
    if isinstance(price_in, (int, float)) and isinstance(price_out, (int, float)):
      prices[str(model)] = (float(price_in), float(price_out))
  return prices


def _coerce_depth(raw_depth: Any) -> int:
  # Map DLE depth labels to the numeric sections required by the pipeline.
  if raw_depth is None:
    return 2
  if isinstance(raw_depth, str):
    normalized = raw_depth.strip().lower()
    if normalized == "highlights":
      return 2
    if normalized == "detailed":
      return 6
    if normalized == "training":
      return 10
    if normalized.isdigit():
      raw_depth = int(normalized)
  try:
    depth = int(raw_depth)
  except (TypeError, ValueError) as exc:
    raise ValueError("Depth must be Highlights, Detailed, Training, or an integer between 2 and 10.") from exc
  if depth < 2:
    raise ValueError("Depth must be at least 2.")
  if depth > 10:
    raise ValueError("Depth exceeds the maximum of 10.")
  return depth
