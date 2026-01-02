"""Orchestration for the two-step AI pipeline."""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from math import ceil
from pathlib import Path
from typing import Any, cast

from app.ai.providers.base import AIModel
from app.ai.router import get_model_for_mode
from app.schema.lesson_models import LessonDocument, SectionBlock
from app.schema.widgets_loader import load_widget_registry


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


class DgsOrchestrator:
  """Coordinates the gatherer and structurer agents."""

  def __init__(
    self,
    *,
    gatherer_provider: str,
    gatherer_model: str | None,
    structurer_provider: str,
    structurer_model: str | None,
    repair_provider: str,
    repair_model: str | None,
    schema_version: str,
  ) -> None:
    self._gatherer_provider = gatherer_provider
    self._gatherer_model_name = gatherer_model
    self._structurer_provider = structurer_provider
    self._structurer_model_name = structurer_model
    self._repair_provider = repair_provider
    self._repair_model_name = repair_model
    self._schema_version = schema_version

  async def generate_lesson(
    self,
    *,
    topic: str,
    prompt: str | None = None,
    constraints: dict[str, Any] | None = None,
    schema_version: str | None = None,
    structurer_model: str | None = None,
    gatherer_model: str | None = None,
    structured_output: bool = True,
    language: str | None = None,
    enable_repair: bool = True,
    progress_callback: Callable[[str, str | None, list[str] | None, bool], None] | None = None,
  ) -> OrchestrationResult:
    """Run the 4-agent pipeline and return lesson JSON."""
    logger = logging.getLogger(__name__)
    logs: list[str] = []
    all_usage: list[dict[str, Any]] = []
    validation_errors: list[str] | None = None

    def _report_progress(
      phase_name: str,
      subphase: str | None,
      messages: list[str] | None = None,
      advance: bool = True,
    ) -> None:
      if progress_callback:
        progress_callback(phase_name, subphase, messages, advance)

    gatherer_model_name = gatherer_model or self._gatherer_model_name
    structurer_model_name = structurer_model or self._structurer_model_name

    log_msg = (
      f"Starting generation for topic: '{topic[:50] + '...' if len(topic) >= 50 else topic}'"
    )
    logs.append(log_msg)
    logger.info(log_msg)

    log_msg = f"Gatherer: {self._gatherer_provider}/{gatherer_model_name or 'default'}"
    logs.append(log_msg)
    logger.info(log_msg)

    log_msg = f"Structurer: {self._structurer_provider}/{structurer_model_name or 'default'}"
    logs.append(log_msg)
    logger.info(log_msg)

    # Derive the number of sections from depth for the KnowledgeBuilder batches.
    depth = _coerce_depth((constraints or {}).get("depth"))
    knowledge_calls = ceil(depth / 2)

    gatherer_model_instance = get_model_for_mode(self._gatherer_provider, gatherer_model_name)
    sections: dict[int, dict[str, Any]] = {}

    for call_index in range(1, knowledge_calls + 1):
      section_start = (call_index - 1) * 2 + 1
      section_end = min(section_start + 1, depth)
      subphase = f"kb_call_{call_index}_of_{knowledge_calls}"
      _report_progress(
        "collect",
        subphase,
        [
          f"KnowledgeBuilder call {call_index}/{knowledge_calls} (sections {section_start}-{section_end})"
        ],
      )

      # Prompt the KnowledgeBuilder for exactly two sections per call.
      gatherer_prompt = _render_gatherer_prompt(
        topic=topic,
        prompt=prompt,
        constraints=constraints,
        language=language,
        depth=depth,
        section_start=section_start,
        section_end=section_end,
      )
      logger.debug("Gatherer Prompt:\n%s", gatherer_prompt)
      try:
        gatherer_response = await gatherer_model_instance.generate(gatherer_prompt)
      except Exception as exc:
        _log_request_failure(
          logger=logger,
          logs=logs,
          agent="KnowledgeBuilder",
          provider=self._gatherer_provider,
          model=_model_name(gatherer_model_instance),
          prompt=gatherer_prompt,
          response=None,
          error=exc,
        )
        logs.append(f"KnowledgeBuilder failed batch {call_index}/{knowledge_calls}.")
        continue
      if gatherer_response.usage:
        all_usage.append(
          {
            "model": _model_name(gatherer_model_instance),
            "agent": "KnowledgeBuilder",
            "purpose": "collect_batch",
            "call_index": f"{call_index}/{knowledge_calls}",
            **gatherer_response.usage,
          }
        )
      log_msg = f"KnowledgeBuilder completed batch {call_index}/{knowledge_calls}"
      logs.append(log_msg)
      logger.info(log_msg)

      # Extract per-section text using deterministic parsing.
      extracted_sections = _extract_sections_from_batch(gatherer_response.content)
      if not extracted_sections:
        _log_request_failure(
          logger=logger,
          logs=logs,
          agent="KnowledgeBuilder",
          provider=self._gatherer_provider,
          model=_model_name(gatherer_model_instance),
          prompt=gatherer_prompt,
          response=gatherer_response.content,
          error=RuntimeError("KnowledgeBuilder returned no extractable sections."),
        )
        continue
      for section in extracted_sections:
        section_index = section["index"]
        if section_index < 1 or section_index > depth:
          logs.append(f"Skipping out-of-range section {section_index}.")
          continue
        sections[section_index] = section
        _report_progress(
          "collect",
          f"extract_section_{section_index}_of_{depth}",
          [f"Extracted section {section_index}/{depth}"],
        )

    # Ensure we collected all requested sections before structuring.
    if len(sections) < depth:
      missing = sorted(set(range(1, depth + 1)) - set(sections.keys()))
      logs.append(f"Missing extracted sections: {missing}")
      logger.warning("Missing extracted sections: %s", missing)

    structurer_model_instance = get_model_for_mode(
      self._structurer_provider, structurer_model_name
    )
    structured_sections: list[dict[str, Any]] = []
    if enable_repair:
      logs.append("Repair is disabled by no-retry policy; failed sections are skipped.")
      logger.info("Repair is disabled by no-retry policy; failed sections are skipped.")

    for section_index in range(1, depth + 1):
      section_data = sections.get(section_index)
      if section_data is None:
        logs.append(f"Skipping missing section {section_index}.")
        logger.warning("Skipping missing section %s.", section_index)
        continue
      section_title = section_data["title"]
      section_text = section_data["content"]

      struct_subphase = f"struct_section_{section_index}_of_{depth}"
      _report_progress(
        "transform",
        struct_subphase,
        [f"Structuring section {section_index}/{depth}: {section_title}"],
      )

      parse_error: str | None = None
      try:
        section_json = await self._generate_section_json(
          topic=topic,
          prompt=prompt,
          section_title=section_title,
          section_text=section_text,
          constraints=constraints,
          schema_version=schema_version or self._schema_version,
          structurer=structurer_model_instance,
          all_usage=all_usage,
          usage_purpose=f"struct_section_{section_index}_of_{depth}",
          agent_name="PlannerStructurer",
          call_index=f"{section_index}/{depth}",
          structured_output=structured_output,
          language=language,
        )
      except RuntimeError as exc:
        parse_error = str(exc)
        prompt_text = _render_section_prompt(
          topic=topic, prompt=prompt, section_title=section_title, section_text=section_text,
          constraints=constraints, schema_version=schema_version or self._schema_version, language=language,
        )
        _log_request_failure(
          logger=logger, logs=logs, agent="PlannerStructurer", provider=self._structurer_provider, model=_model_name(structurer_model_instance),
          prompt=prompt_text, response=None, error=exc,
        )
        logs.append(f"Skipping section {section_index} due to structurer failure.")
        continue

      ok, errors, normalized_section = _validate_section_payload(
        section_json,
        topic=topic,
        section_index=section_index,
      )
      if parse_error:
        errors = [parse_error, *errors]
      if ok and normalized_section is not None:
        _report_progress(
          "transform",
          f"validate_section_{section_index}_of_{depth}",
          [f"Section {section_index} validated."],
        )
        structured_sections.append(normalized_section)
        continue

      validation_errors = errors
      logs.append(f"Section {section_index} failed validation: {errors}")
      logger.error("Section %s failed validation: %s", section_index, errors)
      continue

    _report_progress("transform", "stitch_sections", ["Stitching sections..."])
    # Stitch the validated sections into the final lesson payload.
    lesson_json = {
      "title": topic,
      "blocks": structured_sections,
    }

    _report_progress("validate", "final_validation", ["Validating final lesson..."])
    from app.schema.validate_lesson import validate_lesson

    # Final validation against the full lesson schema + widgets.
    ok, errors, _ = validate_lesson(lesson_json)
    validation_errors = errors if not ok else None

    log_msg = "Generation pipeline complete"
    logs.append(log_msg)
    logger.info(log_msg)

    total_cost = self._calculate_total_cost(all_usage)

    return OrchestrationResult(
      lesson_json=lesson_json,
      provider_a=self._gatherer_provider,
      model_a=_model_name(gatherer_model_instance),
      provider_b=self._structurer_provider,
      model_b=_model_name(structurer_model_instance),
      validation_errors=validation_errors if validation_errors else None,
      logs=logs,
      usage=all_usage,
      total_cost=total_cost,
    )

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

  async def _generate_section_json(
    self,
    *,
    topic: str,
    prompt: str | None,
    section_title: str,
    section_text: str,
    constraints: dict[str, Any] | None,
    schema_version: str,
    structurer: AIModel,
    all_usage: list[dict[str, Any]],
    usage_purpose: str,
    agent_name: str,
    call_index: str,
    structured_output: bool,
    language: str | None,
  ) -> dict[str, Any]:
    """Generate a single section JSON object from extracted knowledge."""

    # Use the section-only schema to keep structured outputs small and focused.
    prompt_text = _render_section_prompt(
      topic=topic,
      prompt=prompt,
      section_title=section_title,
      section_text=section_text,
      constraints=constraints,
      schema_version=schema_version,
      language=language,
    )

    schema = _section_json_schema()
    if structurer.supports_structured_output and structured_output:
      if _is_gemini_model_name(_model_name(structurer)):
        schema = _sanitize_schema_for_gemini(schema, root_schema=schema)
      res = await structurer.generate_structured(prompt_text, schema)
      if res.usage:
        all_usage.append(
          {
            "model": _model_name(structurer),
            "agent": agent_name,
            "purpose": usage_purpose,
            "call_index": call_index,
            **res.usage,
          }
        )
      return res.content

    prompt_with_schema = "\n\n".join(
      [
        prompt_text,
        _format_schema_block(schema, label="JSON SCHEMA (Section)"),
        "Output ONLY valid JSON.",
      ]
    )
    raw = await structurer.generate(prompt_with_schema)
    if raw.usage:
      all_usage.append(
        {
          "model": _model_name(structurer),
          "agent": agent_name,
          "purpose": usage_purpose,
          "call_index": call_index,
          **raw.usage,
        }
      )
    try:
      cleaned = structurer.strip_json_fences(raw.content)
      return cast(dict[str, Any], json.loads(cleaned))
    except json.JSONDecodeError as exc:
      _log_request_failure(
        logger=logging.getLogger(__name__),
        logs=None,
        agent=agent_name,
        provider=self._structurer_provider,
        model=_model_name(structurer),
        prompt=prompt_with_schema,
        response=raw.content,
        error=exc,
      )
      raise RuntimeError(f"Failed to parse section JSON: {exc}") from exc

  async def _repair_section_json(
    self,
    *,
    topic: str,
    prompt: str | None,
    section_title: str,
    section_text: str,
    constraints: dict[str, Any] | None,
    invalid_json: dict[str, Any],
    errors: list[str],
    repairer: AIModel,
    all_usage: list[dict[str, Any]],
    usage_purpose: str,
    call_index: str,
  ) -> dict[str, Any]:
    """Repair a section JSON object using the repairer agent."""
    prompt_text = _render_repair_prompt(
      topic=topic,
      prompt=prompt,
      section_title=section_title,
      section_text=section_text,
      constraints=constraints,
      invalid_json=invalid_json,
      errors=errors,
      widgets_text=_load_widgets_text(),
    )

    schema = _section_json_schema()
    if repairer.supports_structured_output:
      if _is_gemini_model_name(_model_name(repairer)):
        schema = _sanitize_schema_for_gemini(schema, root_schema=schema)
      res = await repairer.generate_structured(prompt_text, schema)
      if res.usage:
        all_usage.append(
          {
            "model": _model_name(repairer),
            "agent": "Repairer",
            "purpose": usage_purpose,
            "call_index": call_index,
            **res.usage,
          }
        )
      return res.content

    prompt_with_schema = "\n\n".join(
      [
        prompt_text,
        _format_schema_block(schema, label="JSON SCHEMA (Section)"),
        "Output ONLY valid JSON.",
      ]
    )
    raw = await repairer.generate(prompt_with_schema)
    if raw.usage:
      all_usage.append(
        {
          "model": _model_name(repairer),
          "agent": "Repairer",
          "purpose": usage_purpose,
          "call_index": call_index,
          **raw.usage,
        }
      )
    try:
      cleaned = repairer.strip_json_fences(raw.content)
      return cast(dict[str, Any], json.loads(cleaned))
    except json.JSONDecodeError as exc:
      _log_request_failure(
        logger=logging.getLogger(__name__),
        logs=None,
        agent="Repairer",
        provider=self._repair_provider,
        model=_model_name(repairer),
        prompt=prompt_with_schema,
        response=raw.content,
        error=exc,
      )
      raise RuntimeError(f"Failed to parse repaired section JSON: {exc}") from exc

  async def _generate_highlights(
    self,
    topic: str,
    prompt: str | None,
    knowledge_base: str,
    structurer: AIModel,
    all_usage: list[dict[str, Any]],
    logs: list[str],
    progress_callback: Callable[[str, list[str] | None], None] | None,
    language: str | None,
    constraints: dict[str, Any] | None,
    schema_version: str,
  ) -> dict[str, Any]:
    """Generate a Highlights lesson in a single pass."""
    if progress_callback:
      progress_callback(
        "transform",
        "structure_highlights",
        ["Structuring Highlights lesson..."],
        True,
      )

    prompt_text = _render_structurer_prompt(
      topic=topic,
      prompt=prompt,
      constraints=constraints,
      schema_version=schema_version,
      idm=knowledge_base,
      language=language,
    )

    # We can reuse the unstructured logic if needed, but for now we use structured
    schema = _lesson_json_schema()
    if structurer.supports_structured_output:
      # sanitized = _sanitize_schema_for_gemini(schema, root_schema=schema)
      # res = await structurer.generate_structured(prompt_text, sanitized)
      try:
        res = await structurer.generate_structured(prompt_text, schema)
      except Exception as exc:
        _log_request_failure(
          logger=logging.getLogger(__name__),
          logs=logs,
          agent="Structurer",
          provider=self._structurer_provider,
          model=_model_name(structurer),
          prompt=prompt_text,
          response=None,
          error=exc,
        )
        logs.append("Highlights structuring failed; returning empty lesson.")
        return {"title": topic, "blocks": []}
      if res.usage:
        all_usage.append(
          {
            "model": _model_name(structurer),
            "purpose": "structure_highlights",
            **res.usage,
          }
        )
      return res.content
    else:
      # Fallback (simplified for brevity here)
      try:
        prompt_with_schema = "\n\n".join(
          [
            prompt_text,
            _format_schema_block(schema, label="JSON SCHEMA (Lesson)"),
            "Output ONLY valid JSON.",
          ]
        )
        raw = await structurer.generate(prompt_with_schema)
        if raw.usage:
          all_usage.append(
            {
              "model": _model_name(structurer),
              "purpose": "structure_highlights_raw",
              **raw.usage,
            }
          )
        cleaned = structurer.strip_json_fences(raw.content)
        return cast(dict[str, Any], json.loads(cleaned))
      except json.JSONDecodeError as exc:
        _log_request_failure(
          logger=logging.getLogger(__name__),
          logs=logs,
          agent="Structurer",
          provider=self._structurer_provider,
          model=_model_name(structurer),
          prompt=prompt_with_schema,
          response=raw.content if "raw" in locals() else None,
          error=exc,
        )
        logs.append("Highlights structuring failed; returning empty lesson.")
        return {"title": topic, "blocks": []}

  async def _generate_detailed(
    self,
    topic: str,
    prompt: str | None,
    knowledge_base: str,
    structurer: AIModel,
    all_usage: list[dict[str, Any]],
    logs: list[str],
    progress_callback: Callable[[str, list[str] | None], None] | None,
    language: str | None,
  ) -> dict[str, Any]:
    """Generate a Detailed lesson in two passes."""
    # Pass 1: Skeleton and first part
    if progress_callback:
      progress_callback(
        "transform",
        "structure_detailed_call_1",
        ["Structuring Detailed lesson (Call 1/2)..."],
        True,
      )

    # For simplicity in this implementation, we do one full generation and one expansion/detail call
    full_res = await self._generate_highlights(
      topic=topic,
      prompt=prompt,
      knowledge_base=knowledge_base,
      structurer=structurer,
      all_usage=all_usage,
      logs=logs,
      progress_callback=None,
      language=language,
      constraints={"length": "Detailed"},
      schema_version=self._schema_version,
    )

    if progress_callback:
      progress_callback(
        "transform",
        "structure_detailed_call_2",
        ["Expanding content details (Call 2/2)..."],
        True,
      )

    expand_prompt = f"Expand the following lesson with more detailed activities and deep-dive content:\n{json.dumps(full_res)}"
    expand_schema = _lesson_json_schema()
    try:
      res = await structurer.generate_structured(
        expand_prompt, _sanitize_schema_for_gemini(expand_schema, root_schema=expand_schema)
      )
    except Exception as exc:
      _log_request_failure(
        logger=logging.getLogger(__name__),
        logs=logs,
        agent="Structurer",
        provider=self._structurer_provider,
        model=_model_name(structurer),
        prompt=expand_prompt,
        response=None,
        error=exc,
      )
      logs.append("Detailed expansion failed; returning initial structured content.")
      return full_res
    if res.usage:
      all_usage.append(
        {
          "model": _model_name(structurer),
          "purpose": "structure_detailed_expand",
          **res.usage,
        }
      )

    return res.content

  async def _generate_training(
    self,
    topic: str,
    prompt: str | None,
    knowledge_base: str,
    sections_count: int,
    structurer: AIModel,
    all_usage: list[dict[str, Any]],
    logs: list[str],
    progress_callback: Callable[[str, list[str] | None], None] | None,
    language: str | None,
  ) -> dict[str, Any]:
    """Generate a Training lesson by looping over sections."""
    if progress_callback:
      progress_callback(
        "transform",
        "structure_training_plan",
        [f"Planning {sections_count} sections..."],
        True,
      )

    # 1. Plan sections
    plan_prompt = f"Based on this knowledge: {knowledge_base[:2000]}, plan {sections_count} section titles for a lesson on {topic}."
    plan_schema = {
      "type": "object",
      "properties": {
        "title": {"type": "string"},
        "sections": {
          "type": "array",
          "items": {"type": "object", "properties": {"title": {"type": "string"}}},
        },
      },
    }
    try:
      res_plan = await structurer.generate_structured(
        plan_prompt, _sanitize_schema_for_gemini(plan_schema, root_schema=plan_schema)
      )
    except Exception as exc:
      _log_request_failure(
        logger=logging.getLogger(__name__),
        logs=logs,
        agent="Structurer",
        provider=self._structurer_provider,
        model=_model_name(structurer),
        prompt=plan_prompt,
        response=None,
        error=exc,
      )
      logs.append("Training plan generation failed; returning empty training lesson.")
      return {"title": topic, "sections": [], "meta": {"topic": topic}}
    if res_plan.usage:
      all_usage.append(
        {
          "model": _model_name(structurer),
          "purpose": "structure_training_plan",
          **res_plan.usage,
        }
      )

    # 2. Generate sections
    final_sections = []
    for i in range(sections_count):
      section_data = res_plan.content.get("sections", [])
      title = (
        section_data[i].get("title", f"Section {i + 1}")
        if i < len(section_data)
        else f"Section {i + 1}"
      )
      if progress_callback:
        progress_callback(
          "transform",
          f"struct_section_{i + 1}_of_{sections_count}",
          [f"Generating section {i + 1}/{sections_count}: {title}"],
          True,
        )

      sec_prompt = f"Generate a detailed content section for '{title}' within a lesson on {topic}. Knowledge: {knowledge_base[:1000]}"
      # Simplified section content schema
      try:
        sec_res = await structurer.generate_structured(
          sec_prompt, {"type": "object", "properties": {"content": {"type": "string"}}}
        )
      except Exception as exc:
        _log_request_failure(
          logger=logging.getLogger(__name__),
          logs=logs,
          agent="Structurer",
          provider=self._structurer_provider,
          model=_model_name(structurer),
          prompt=sec_prompt,
          response=None,
          error=exc,
        )
        logs.append(f"Skipping training section {i + 1} due to structurer failure.")
        continue
      if sec_res.usage:
        all_usage.append(
          {
            "model": _model_name(structurer),
            "purpose": f"structure_training_sec_{i + 1}",
            **sec_res.usage,
          }
        )

      final_sections.append({"title": title, "content": sec_res.content.get("content", "")})

    return {
      "title": res_plan.content.get("title", topic),
      "sections": final_sections,
      "meta": {"topic": topic},
    }


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


def _render_gatherer_prompt(
  *,
  topic: str,
  prompt: str | None,
  constraints: dict[str, Any] | None,
  language: str | None,
  depth: int,
  section_start: int,
  section_end: int,
) -> str:
  prompt_template = _load_prompt("gatherer.md")
  parts = [prompt_template, f"Topic: {topic}"]
  if prompt:
    parts.append(f"User Prompt: {prompt}")
  if language:
    parts.append(f"Language: {language}")
  parts.append(f"Constraints: {constraints or {} }")
  parts.append(f"Total Sections: {depth}")
  parts.append(f"Return Sections: {section_start}-{section_end}")
  return "\n".join(parts)


def _render_structurer_prompt(
  *,
  topic: str,
  prompt: str | None,
  constraints: dict[str, Any] | None,
  schema_version: str,
  idm: str,
  language: str | None,
) -> str:
  prompt_template = _load_prompt("structurer.md")
  return "\n".join(
    [
      prompt_template,
      "=== BEGIN REQUEST CONTEXT ===",
      f"Topic: {topic}",
      f"User Prompt: {prompt or ''}",
      f"Language: {language or ''}",
      f"Constraints: {constraints or {} }",
      f"Schema Version: {schema_version}",
      "=== END REQUEST CONTEXT ===",
      "=== BEGIN AGENT INPUT (IDM) ===",
      idm,
      "=== END AGENT INPUT (IDM) ===",
    ]
  )


def _render_section_prompt(
  *,
  topic: str,
  prompt: str | None,
  section_title: str,
  section_text: str,
  constraints: dict[str, Any] | None,
  schema_version: str,
  language: str | None,
) -> str:
  prompt_template = _load_prompt("structurer_section.md")
  return "\n".join(
    [
      prompt_template,
      "=== BEGIN REQUEST CONTEXT ===",
      f"Topic: {topic}",
      f"User Prompt: {prompt or ''}",
      f"Language: {language or ''}",
      f"Constraints: {constraints or {} }",
      f"Schema Version: {schema_version}",
      "=== END REQUEST CONTEXT ===",
      "=== BEGIN WIDGET RULES ===",
      _load_widgets_text(),
      "=== END WIDGET RULES ===",
      "=== BEGIN AGENT INPUT (SECTION TITLE) ===",
      section_title,
      "=== END AGENT INPUT (SECTION TITLE) ===",
      "=== BEGIN AGENT INPUT (SECTION CONTENT) ===",
      section_text,
      "=== END AGENT INPUT (SECTION CONTENT) ===",
    ]
  )


def _coerce_depth(raw_depth: Any) -> int:
  if raw_depth is None:
    return 2
  try:
    depth = int(raw_depth)
  except (TypeError, ValueError) as exc:
    raise ValueError("Depth must be an integer between 2 and 10.") from exc
  if depth < 2:
    raise ValueError("Depth must be at least 2.")
  if depth > 10:
    raise ValueError("Depth exceeds the maximum of 10.")
  return depth


def _extract_sections_from_batch(text: str) -> list[dict[str, Any]]:
  """Extract numbered 'Section N - Title' blocks from a KnowledgeBuilder batch.

  This supports minor formatting variations, including:
  - Extra whitespace
  - Different dash characters between section number and title: '-', '–', '—'

  Returns a list of dicts: {index: int, title: str, content: str}
  """

  # Match section headers like:
  #   Section 1 - Title
  #   Section 2 – Title
  #   Section 3 — Title
  header_re = re.compile(r"(?m)^\s*Section\s*(\d+)\s*[-–—]\s*([^\n]+?)\s*$")

  matches = list(header_re.finditer(text))
  if not matches:
    return []

  extracted: list[dict[str, Any]] = []

  for i, m in enumerate(matches):
    index = int(m.group(1))
    title = m.group(2).strip()

    content_start = m.end()
    content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

    content = text[content_start:content_end].strip("\n")
    # Normalize trailing whitespace per line without losing intentional indentation.
    content = "\n".join(line.rstrip() for line in content.splitlines()).strip()

    extracted.append(
      {
        "index": index,
        "title": title,
        "content": content,
      }
    )

  return extracted


def _wrap_section_for_validation(
  section_json: dict[str, Any],
  *,
  topic: str,
  section_index: int,
) -> dict[str, Any]:
  return {
    "title": f"{topic} - Section {section_index}",
    "blocks": [section_json],
  }


def _validate_section_payload(
  section_json: dict[str, Any],
  *,
  topic: str,
  section_index: int,
) -> tuple[bool, list[str], dict[str, Any] | None]:
  from app.schema.validate_lesson import validate_lesson

  payload = _wrap_section_for_validation(section_json, topic=topic, section_index=section_index)
  ok, errors, model = validate_lesson(payload)
  if not ok or model is None or not model.blocks:
    return False, errors, None
  # section_payload = model.blocks[0].model_dump(mode="python", by_alias=True)
  # return True, errors, cast(dict[str, Any], section_payload)
  return True, errors, cast(dict[str, Any], section_json)


def _deterministic_repair_section(
  section_json: dict[str, Any],
  errors: list[str],
  *,
  topic: str,
  section_index: int,
) -> dict[str, Any]:
  from app.ai.deterministic_repair import attempt_deterministic_repair

  payload = _wrap_section_for_validation(section_json, topic=topic, section_index=section_index)
  repaired = attempt_deterministic_repair(payload, errors)
  blocks = repaired.get("blocks")
  if isinstance(blocks, list) and blocks:
    first_block = blocks[0]
    if isinstance(first_block, dict):
      return first_block
  return section_json


def _render_repair_prompt(
  *,
  topic: str,
  prompt: str | None,
  section_title: str,
  section_text: str,
  constraints: dict[str, Any] | None,
  invalid_json: dict[str, Any],
  errors: list[str],
  widgets_text: str,
) -> str:
  """Render the repair agent prompt with validation errors."""
  import json

  prompt_template = _load_prompt("repair.md")
  return "\n".join(
    [
      prompt_template,
      f"Topic: {topic}",
      f"User Prompt: {prompt or ''}",
      f"Section Title: {section_title}",
      "Section Content:",
      section_text,
      f"Constraints: {constraints or {} }",
      "Widgets:",
      widgets_text,
      "\nInvalid JSON:",
      json.dumps(invalid_json, indent=2),
      "\nValidation Errors:",
      "\n".join(f"- {error}" for error in errors),
      "\nProvide the corrected JSON:",
    ]
  )


@lru_cache(maxsize=1)
def _load_prompt(name: str) -> str:
  try:
    path = Path(__file__).with_name("prompts") / name
    return path.read_text(encoding="utf-8").strip()
  except (FileNotFoundError, PermissionError, UnicodeDecodeError) as e:
    raise RuntimeError(f"Failed to load prompt '{name}': {e}") from e


@lru_cache(maxsize=1)
def _load_widgets_text() -> str:
  try:
    path = Path(__file__).parents[1] / "schema" / "widgets_prompt.md"
    return path.read_text(encoding="utf-8").strip()
  except (FileNotFoundError, PermissionError, UnicodeDecodeError) as e:
    raise RuntimeError(f"Failed to load widgets documentation: {e}") from e


def _format_schema_block(schema: dict[str, Any], *, label: str) -> str:
  schema_json = json.dumps(schema, indent=2, ensure_ascii=True)
  return "\n".join(
    [
      f"=== BEGIN {label} ===",
      schema_json,
      f"=== END {label} ===",
    ]
  )


@lru_cache(maxsize=1)
def _lesson_json_schema() -> dict[str, Any]:
  json_schema: dict[str, Any] = LessonDocument.model_json_schema(
    by_alias=True, ref_template="#/$defs/{model}", mode="validation"
  )
  load_widget_registry(Path(__file__).parents[1] / "schema" / "widgets_prompt.md")
  return json_schema
  # return LessonDocument.model_json_schema()


@lru_cache(maxsize=1)
def _section_json_schema() -> dict[str, Any]:
  json_schema: dict[str, Any] = SectionBlock.model_json_schema(
    by_alias=True,
    ref_template="#/$defs/{model}",
    mode="validation",
  )
  load_widget_registry(Path(__file__).parents[1] / "schema" / "widgets_prompt.md")
  return json_schema


def _is_gemini_model_name(name: str) -> bool:
  return name.startswith("gemini-")


def _sanitize_schema_for_gemini(
  schema: Any,
  root_schema: dict[str, Any] | None = None,
  visited: set[str] | None = None,
) -> Any:
  """\
  Sanitize a JSON Schema for Gemini SDK structured output.

  The google-genai schema transformer is strict and can crash if it encounters
  non-schema arrays (e.g., `required: ["a", "b"]`) or unexpected primitives in
  places it assumes are schema objects. It also fails if object schemas have
  empty 'properties'.

  Strategy:
  - Keep a minimal subset of JSON Schema keywords.
  - Resolve $ref pointers using the definitions in root_schema logic to avoid
    leaving empty objects or references that the SDK doesn't handle well.
  - Drop metadata keys (title/description/examples/default/etc.).
  - Drop `required` entirely (we validate with our own validator afterwards).

  Args:
      schema: The schema node to sanitize.
      root_schema: The full root schema containing $defs or definitions (used for $ref resolution).
      visited: Set of visited $ref paths to prevent infinite recursion.
  """
  if visited is None:
    visited = set()

  if schema is None:
    return {"type": "object", "properties": {}}

  # Primitives in schema positions can crash the transformer.
  if isinstance(schema, str):
    return {"type": "object", "properties": {}}

  if isinstance(schema, (int, float, bool)):
    return schema

  if isinstance(schema, list):
    # Only keep dict-like schemas in lists; drop primitives like strings.
    out: list[Any] = []
    for item in schema:
      if isinstance(item, dict):
        out.append(_sanitize_schema_for_gemini(item, root_schema, visited))
    return out

  if not isinstance(schema, dict):
    return {"type": "object", "properties": {}}

  # Handle $ref resolution
  if "$ref" in schema:
    ref_path = schema["$ref"]
    # Basic cycle detection
    if ref_path in visited:
      # Recursive reference: bail out to a generic object to stop infinite loop
      return {"type": "object", "properties": {}}

    # If we have definitions, try to resolve the ref
    if root_schema:
      defs = root_schema.get("$defs") or root_schema.get("definitions")
      if defs and isinstance(defs, dict):
        # Assume ref is like "#/$defs/WidgetName"
        parts = ref_path.split("/")
        if len(parts) >= 3:
          def_name = parts[-1]
          if def_name in defs:
            # Found the definition! Sanitize it recursively
            new_visited = visited.copy()
            new_visited.add(ref_path)
            return _sanitize_schema_for_gemini(defs[def_name], root_schema, new_visited)

    # Fallback if we can't resolve or no definitions
    return {"type": "object", "properties": {}}

  # Allowed keys that Gemini's transformer generally tolerates.
  ALLOWED_KEYS: set[str] = {
    "type",
    "properties",
    "items",
    "anyOf",
    "oneOf",
    "allOf",
    "enum",
    "format",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "pattern",
  }

  # Keys we explicitly drop (metadata / complex features).
  # Note: additionalProperties is dropped because Gemini SDK's GenerateContentConfig
  # does not accept it in response_json_schema and will raise a validation error.
  DROP_KEYS: set[str] = {
    "title",
    "description",
    "examples",
    "default",
    "$defs",
    "definitions",
    "additionalProperties",
  }

  cleaned: dict[str, Any] = {}

  for key, value in schema.items():
    if value is None:
      continue
    if key in DROP_KEYS:
      continue
    if key not in ALLOWED_KEYS and key != "required":
      # Ignore other JSON Schema keywords to keep transformer happy.
      continue

    if key == "required":
      # Filter required fields to ensure they exist in 'properties'
      # to avoid referencing undefined keys which can crash the API.
      if isinstance(value, list) and isinstance(schema.get("properties"), dict):
        props = schema.get("properties", {})
        valid_required = [f for f in value if f in props]
        if valid_required:
          cleaned["required"] = valid_required
      continue

    if key == "type":
      # Pydantic may emit `type: ["string", "null"]`.
      if isinstance(value, list):
        types = [t for t in value if isinstance(t, str) and t != "null"]
        cleaned["type"] = types[0] if types else "object"
      elif isinstance(value, str) and value != "null":
        cleaned["type"] = value
      else:
        cleaned["type"] = "object"
      continue

    if key in ("anyOf", "oneOf", "allOf"):
      if isinstance(value, list):
        schemas: list[dict[str, Any]] = []
        for item in value:
          if isinstance(item, dict) and item.get("type") != "null":
            # We allow $ref here now because we resolve it above (if it was the only key)
            # But inside anyOf/oneOf, item might be just {"$ref": ...}
            # So we recursively sanitize it.
            sanitized_item = _sanitize_schema_for_gemini(item, root_schema, visited)
            if isinstance(sanitized_item, dict):
              schemas.append(sanitized_item)
        if schemas:
          cleaned[key] = schemas
      continue

    if key == "properties":
      if isinstance(value, dict):
        props: dict[str, Any] = {}
        for prop_name, prop_schema in value.items():
          if isinstance(prop_schema, dict):
            props[prop_name] = _sanitize_schema_for_gemini(
              prop_schema, root_schema, visited
            )
          else:
            # Coerce unexpected property schema primitives.
            props[prop_name] = {"type": "object", "properties": {}}
        cleaned["properties"] = props
      continue

    if key == "items":
      if isinstance(value, dict):
        cleaned["items"] = _sanitize_schema_for_gemini(value, root_schema, visited)
      elif isinstance(value, list):
        # Prefer first dict-like schema.
        first = next((v for v in value if isinstance(v, dict)), None)
        cleaned["items"] = (
          _sanitize_schema_for_gemini(first, root_schema, visited)
          if first
          else {"type": "object", "properties": {}}
        )
      else:
        cleaned["items"] = {"type": "object", "properties": {}}
      continue

    # Simple scalar keys
    if isinstance(value, (str, int, float, bool)):
      cleaned[key] = value
    elif isinstance(value, dict):
      cleaned[key] = _sanitize_schema_for_gemini(value, root_schema, visited)
    # else: drop

  # Ensure we always have a type for object schemas.
  if "type" not in cleaned:
    if "properties" in cleaned:
      cleaned["type"] = "object"
    elif "items" in cleaned:
      cleaned["type"] = "array"
    else:
      cleaned["type"] = "object"

  return cleaned
