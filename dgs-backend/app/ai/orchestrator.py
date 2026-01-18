"""Orchestration for the multi-agent AI pipeline."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Literal, Optional

from app.ai.agents import GathererAgent, GathererStructurerAgent, PlannerAgent, RepairerAgent, StitcherAgent, StructurerAgent
from app.ai.pipeline.contracts import GenerationRequest, JobContext, LessonPlan, RepairInput, SectionDraft, StructuredSection, StructuredSectionBatch
from app.ai.providers.base import AIModel
from app.ai.router import get_model_for_mode
from app.schema.service import SchemaService

OptStr = str | None
Msgs = list[str] | None
SectionStatus = Literal["generating", "retrying", "completed"]
ProgressCallback = (
  Callable[[str, OptStr, Msgs, bool, dict[str, Any] | None, Optional["SectionProgressUpdate"]], None] | None
)
MERGED_DEFAULT_MODEL = "xiaomi/mimo-v2-flash:free"


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


class OrchestrationError(RuntimeError):
  """Raised when the orchestration pipeline encounters a fatal error."""

  def __init__(self, message: str, *, logs: list[str]) -> None:
    """Store the failure message and a log snapshot for upstream handlers."""
    super().__init__(message)
    # Keep a snapshot of logs to surface in API/job responses.
    self.logs = logs


@dataclass(frozen=True)
class SectionProgressUpdate:
  """Section-level metadata for streaming job progress."""

  index: int
  title: str | None
  status: SectionStatus
  retry_count: int | None = None
  completed_sections: int | None = None


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
    merge_gatherer_structurer: bool = False,
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
    self._merge_gatherer_structurer = merge_gatherer_structurer

  async def generate_lesson(
    self,
    *,
    topic: str,
    details: str | None = None,
    blueprint: str | None = None,
    teaching_style: list[str] | None = None,
    learner_level: str | None = None,
    depth: str | None = None,
    widgets: list[str] | None = None,
    schema_version: str | None = None,
    structurer_model: str | None = None,
    gatherer_model: str | None = None,
    structured_output: bool = True,
    language: str | None = None,
    enable_repair: bool = True,
    progress_callback: ProgressCallback = None,
    section_filter: set[int] | None = None,
  ) -> OrchestrationResult:
    """Run the 5-agent pipeline and return lesson JSON."""
    logger = logging.getLogger(__name__)
    logs: list[str] = []
    all_usage: list[dict[str, Any]] = []
    validation_errors: list[str] | None = None
    # Track artifacts so failure logs can include the latest built data.
    lesson_plan: LessonPlan | None = None
    draft_artifacts: list[dict[str, Any]] = []
    structured_artifacts: list[dict[str, Any]] = []
    repair_artifacts: list[dict[str, Any]] = []

    def _report_progress(
      phase_name: str,
      subphase: OptStr,
      messages: Msgs = None,
      advance: bool = True,
      partial_json: dict[str, Any] | None = None,
      section_progress: SectionProgressUpdate | None = None,
    ) -> None:
      # Stream progress updates to the worker when configured.
      if progress_callback:
        progress_callback(phase_name, subphase, messages, advance, partial_json, section_progress)

    def _build_partial_lesson(sections: list[StructuredSection]) -> dict[str, Any]:
      """Build a partial lesson JSON from the completed sections."""
      # Preserve section order while streaming the latest structured payloads.
      ordered_sections = sorted(sections, key=lambda section: section.section_number)
      shorthand_sections = StitcherAgent._output_dle_shorthand(ordered_sections)
      return {"title": topic, "blocks": [section.payload for section in shorthand_sections]}

    def _section_progress(
      section_index: int,
      *,
      title: str | None,
      status: SectionStatus,
      retry_count: int | None = None,
      completed_sections: int | None = None,
    ) -> SectionProgressUpdate:
      """Normalize section progress updates with 0-based indexing."""
      # Convert 1-based section numbers to the 0-based indices expected by the client.
      zero_based_index = section_index - 1
      return SectionProgressUpdate(
        index=zero_based_index,
        title=title,
        status=status,
        retry_count=retry_count,
        completed_sections=completed_sections,
      )

    gatherer_model_name = gatherer_model or self._gatherer_model_name
    structurer_model_name = structurer_model or self._structurer_model_name
    planner_model_name = self._planner_model_name or structurer_model_name
    # Toggle merged gatherer+structurer mode based on the environment flag.
    merge_enabled = self._merge_gatherer_structurer
    merged_model_name = gatherer_model_name or MERGED_DEFAULT_MODEL

    topic_preview = topic[:50] + "..." if len(topic) >= 50 else topic
    log_msg = f"Starting generation for topic: '{topic_preview}'"
    logs.append(log_msg)
    logger.info(log_msg)

    if merge_enabled:
      log_msg = f"Gatherer+Structurer (merged): {self._gatherer_provider}/{merged_model_name or 'default'}"
      logs.append(log_msg)
      logger.info(log_msg)

    else:
      log_msg = f"Gatherer: {self._gatherer_provider}/{gatherer_model_name or 'default'}"
      logs.append(log_msg)
      logger.info(log_msg)

    log_msg = f"Planner: {self._planner_provider}/{planner_model_name or 'default'}"
    logs.append(log_msg)
    logger.info(log_msg)

    log_msg = f"Structurer: {self._structurer_provider}/{structurer_model_name or 'default'}"
    logs.append(log_msg)
    logger.info(log_msg)

    lang = language
    request = GenerationRequest(
      topic=topic,
      prompt=details,
      depth=depth,
      section_count=_depth_profile(depth),
      blueprint=blueprint,
      teaching_style=teaching_style,
      learner_level=learner_level,
      language=lang,
      widgets=widgets,
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

    if merge_enabled:
      gatherer_model_instance = get_model_for_mode(
        self._gatherer_provider, merged_model_name, agent="gatherer_structurer"
      )

    else:
      gatherer_model_instance = get_model_for_mode(self._gatherer_provider, gatherer_model_name, agent="gatherer")

    planner_model_instance = get_model_for_mode(self._planner_provider, planner_model_name, agent="planner")
    structurer_model_instance = get_model_for_mode(self._structurer_provider, structurer_model_name, agent="structurer")
    repairer_model_instance = get_model_for_mode(self._repair_provider, self._repair_model_name, agent="repairer")

    schema = self._schema_service
    use = usage_sink
    gatherer_prov = self._gatherer_provider
    planner_prov = self._planner_provider
    structurer_prov = self._structurer_provider
    repair_prov = self._repair_provider
    planner_agent = PlannerAgent(model=planner_model_instance, prov=planner_prov, schema=schema, use=use)

    if merge_enabled:
      gatherer_agent = None
      gatherer_structurer_agent = GathererStructurerAgent(
        model=gatherer_model_instance, prov=gatherer_prov, schema=schema, use=use
      )

    else:
      gatherer_agent = GathererAgent(model=gatherer_model_instance, prov=gatherer_prov, schema=schema, use=use)
      gatherer_structurer_agent = None

    structurer_agent = StructurerAgent(model=structurer_model_instance, prov=structurer_prov, schema=schema, use=use)
    repairer_agent = RepairerAgent(model=repairer_model_instance, prov=repair_prov, schema=schema, use=use)
    stitcher_agent = StitcherAgent(model=structurer_model_instance, prov=structurer_prov, schema=schema, use=use)

    async def _process_structured_section(
      *, draft: SectionDraft, structured: StructuredSection, section_index: int
    ) -> StructuredSection | None:
      """Validate, optionally repair, and finalize a structured section."""
      nonlocal validation_errors

      if structured.validation_errors and not enable_repair:
        # Treat validation errors as fatal to avoid returning partial lessons.
        validation_errors = structured.validation_errors
        error_message = f"Section {section_index} failed validation: {structured.validation_errors}"
        logs.append(error_message)
        logger.error("Section %s failed validation: %s", section_index, structured.validation_errors)
        _report_progress(
          "transform", f"validate_section_{section_index}_of_{section_count}", [error_message], advance=False
        )
        raise OrchestrationError(error_message, logs=list(logs))

      section_json = structured.payload

      if enable_repair:
        # Attempt repair to avoid failing on transient schema errors.
        repair_input = RepairInput(section=draft, structured=structured)

        # Mark the section as retrying when structured validation reports errors.
        if structured.validation_errors:
          _report_progress(
            "transform",
            f"repair_section_{section_index}_of_{section_count}",
            [f"Retrying section {section_index}/{section_count} after validation failure."],
            advance=False,
            partial_json=_build_partial_lesson(structured_sections),
            section_progress=_section_progress(
              section_index,
              title=draft.title,
              status="retrying",
              retry_count=1,
              completed_sections=len(structured_sections),
            ),
          )

        try:
          repair_result = await repairer_agent.run(repair_input, ctx)

        except Exception as exc:
          # Treat repair failures as fatal to avoid incomplete lessons.
          repair_model = _model_name(repairer_model_instance)
          _log_request_failure(
            logger=logger,
            logs=logs,
            agent="Repairer",
            provider=self._repair_provider,
            model=repair_model,
            prompt=None,
            response=None,
            error=exc,
          )
          _log_pipeline_snapshot(
            logger=logger,
            logs=logs,
            agent="Repairer",
            error=exc,
            lesson_plan=lesson_plan,
            draft_artifacts=draft_artifacts,
            structured_artifacts=structured_artifacts,
            repair_artifacts=repair_artifacts,
          )
          error_message = f"Repairer failed for section {section_index}/{section_count}: {exc}"
          logs.append(error_message)
          _report_progress(
            "transform", f"repair_section_{section_index}_of_{section_count}", [error_message], advance=False
          )
          raise OrchestrationError(error_message, logs=list(logs)) from exc

        repair_artifacts.append(repair_result.model_dump(mode="python"))

        if repair_result.errors:
          # Fail fast when repair cannot produce a valid section.
          validation_errors = repair_result.errors
          error_message = f"Section {section_index} failed repair validation: {repair_result.errors}"
          logs.append(error_message)
          logger.error("Section %s failed repair validation: %s", section_index, repair_result.errors)
          _report_progress(
            "transform", f"repair_section_{section_index}_of_{section_count}", [error_message], advance=False
          )
          raise OrchestrationError(error_message, logs=list(logs))
        section_json = repair_result.fixed_json

      validate_subphase = f"validate_section_{section_index}_of_{section_count}"
      _report_progress("transform", validate_subphase, [f"Section {section_index} validated."])
      return StructuredSection(section_number=section_index, json=section_json, validation_errors=[])

    _report_progress("plan", "planner_start", ["Planning lesson sections..."])

    try:
      lesson_plan = await planner_agent.run(request, ctx)
    except Exception as exc:
      # Fail fast when the planner cannot produce a valid plan.
      planner_model = _model_name(planner_model_instance)
      _log_request_failure(
        logger=logger,
        logs=logs,
        agent="Planner",
        provider=planner_prov,
        model=planner_model,
        prompt=None,
        response=None,
        error=exc,
      )
      _log_pipeline_snapshot(
        logger=logger,
        logs=logs,
        agent="Planner",
        error=exc,
        lesson_plan=lesson_plan,
        draft_artifacts=draft_artifacts,
        structured_artifacts=structured_artifacts,
        repair_artifacts=repair_artifacts,
      )
      error_message = f"Planner failed: {exc}"
      logs.append(error_message)
      _report_progress("plan", "planner_failed", [error_message], advance=False)
      raise OrchestrationError(error_message, logs=list(logs)) from exc

    _report_progress("plan", "planner_complete", ["Lesson plan ready."])

    sections: dict[int, SectionDraft] = {}
    structured_sections: list[StructuredSection] = []

    section_count = len(lesson_plan.sections)
    # Restrict orchestration to a subset of sections when retrying.
    target_sections = set(section_filter) if section_filter else None
    target_section_count = len(target_sections) if target_sections is not None else section_count

    for plan_section in lesson_plan.sections:
      section_index = plan_section.section_number

      if target_sections is not None and section_index not in target_sections:
        continue

      if merge_enabled:
        merge_subphase = f"gather_struct_section_{section_index}_of_{section_count}"
        merge_msg = f"Gathering+structuring section {section_index}/{section_count}: {plan_section.title}"
        _report_progress(
          "transform",
          merge_subphase,
          [merge_msg],
          section_progress=_section_progress(
            section_index, title=plan_section.title, status="generating", completed_sections=len(structured_sections)
          ),
        )

        try:
          structured = await gatherer_structurer_agent.run(plan_section, ctx)

        except Exception as exc:
          # Stop immediately on merged gatherer/structurer failures.
          merged_model = _model_name(gatherer_model_instance)
          _log_request_failure(
            logger=logger,
            logs=logs,
            agent="GathererStructurer",
            provider=gatherer_prov,
            model=merged_model,
            prompt=None,
            response=None,
            error=exc,
          )
          _log_pipeline_snapshot(
            logger=logger,
            logs=logs,
            agent="GathererStructurer",
            error=exc,
            lesson_plan=lesson_plan,
            draft_artifacts=draft_artifacts,
            structured_artifacts=structured_artifacts,
            repair_artifacts=repair_artifacts,
          )
          error_message = f"Gatherer-structurer failed section {section_index}/{section_count}: {exc}"
          logs.append(error_message)
          _report_progress("transform", merge_subphase, [error_message], advance=False)
          raise OrchestrationError(error_message, logs=list(logs)) from exc

        if section_index < 1 or section_index > section_count:
          # Treat out-of-range indices as fatal planner/agent mismatches.
          error_message = f"Received out-of-range section index {section_index}."
          logs.append(error_message)
          logger.error("Out-of-range section index %s.", section_index)
          _report_progress("transform", merge_subphase, [error_message], advance=False)
          raise OrchestrationError(error_message, logs=list(logs))

        # Preserve draft context for repair by synthesizing a minimal SectionDraft.
        draft = SectionDraft(
          section_number=section_index,
          title=plan_section.title,
          plan_section=plan_section,
          raw_text="Merged gatherer-structurer output (raw gatherer text unavailable).",
          extracted_parts=None,
        )
        sections[section_index] = draft
        draft_artifacts.append(draft.model_dump(mode="python"))
        structured_artifacts.append(structured.model_dump(mode="python"))
        structured_section = await _process_structured_section(
          draft=draft, structured=structured, section_index=section_index
        )

        if structured_section is not None:
          structured_sections.append(structured_section)
          _report_progress(
            "transform",
            f"section_{section_index}_ready",
            [f"Section {section_index}/{section_count} ready."],
            advance=False,
            partial_json=_build_partial_lesson(structured_sections),
            section_progress=_section_progress(
              section_index, title=draft.title, status="completed", completed_sections=len(structured_sections)
            ),
          )

      else:
        gather_subphase = f"gather_section_{section_index}_of_{section_count}"
        gather_msg = f"Gathering section {section_index}/{section_count}: {plan_section.title}"
        _report_progress(
          "collect",
          gather_subphase,
          [gather_msg],
          section_progress=_section_progress(
            section_index, title=plan_section.title, status="generating", completed_sections=len(structured_sections)
          ),
        )

        try:
          draft = await gatherer_agent.run(plan_section, ctx)

        except Exception as exc:
          # Stop immediately on gatherer failures to avoid partial lessons.
          gather_model = _model_name(gatherer_model_instance)
          _log_request_failure(
            logger=logger,
            logs=logs,
            agent="Gatherer",
            provider=gatherer_prov,
            model=gather_model,
            prompt=None,
            response=None,
            error=exc,
          )
          _log_pipeline_snapshot(
            logger=logger,
            logs=logs,
            agent="Gatherer",
            error=exc,
            lesson_plan=lesson_plan,
            draft_artifacts=draft_artifacts,
            structured_artifacts=structured_artifacts,
            repair_artifacts=repair_artifacts,
          )
          error_message = f"Gatherer failed section {section_index}/{section_count}: {exc}"
          logs.append(error_message)
          _report_progress("collect", gather_subphase, [error_message], advance=False)
          raise OrchestrationError(error_message, logs=list(logs)) from exc

        if section_index < 1 or section_index > section_count:
          # Treat out-of-range indices as fatal planner/agent mismatches.
          error_message = f"Received out-of-range section index {section_index}."
          logs.append(error_message)
          logger.error("Out-of-range section index %s.", section_index)
          _report_progress("collect", gather_subphase, [error_message], advance=False)
          raise OrchestrationError(error_message, logs=list(logs))

        sections[section_index] = draft
        draft_artifacts.append(draft.model_dump(mode="python"))
        extract_subphase = f"extract_section_{section_index}_of_{section_count}"
        extract_msg = f"Extracted section {section_index}/{section_count}"
        _report_progress(
          "collect",
          extract_subphase,
          [extract_msg],
          section_progress=_section_progress(
            section_index, title=draft.title, status="generating", completed_sections=len(structured_sections)
          ),
        )
        section_index += 1

    # Ensure we collected all requested sections before structuring.

    if len(sections) < target_section_count:
      # Treat missing sections as fatal to avoid returning partial lessons.
      missing = sorted(set(range(1, section_count + 1)) - set(sections.keys()))

      if target_sections is not None:
        missing = sorted(set(target_sections) - set(sections.keys()))

      error_message = f"Missing extracted sections: {missing}"
      logs.append(error_message)
      logger.error("Missing extracted sections: %s", missing)
      _report_progress("collect", "missing_sections", [error_message], advance=False)
      raise OrchestrationError(error_message, logs=list(logs))

    if not enable_repair:
      # Note that repair is disabled so invalid sections will stop the pipeline.
      logs.append("Repair is disabled; pipeline will stop on invalid sections.")
      logger.info("Repair is disabled; pipeline will stop on invalid sections.")

    if not merge_enabled:
      section_indexes = list(range(1, section_count + 1))

      if target_sections is not None:
        section_indexes = sorted(target_sections)

      for section_index in section_indexes:
        draft = sections.get(section_index)

        if draft is None:
          logs.append(f"Skipping missing section {section_index}.")
          logger.warning("Skipping missing section %s.", section_index)
          continue

        struct_subphase = f"struct_section_{section_index}_of_{section_count}"
        struct_msg = f"Structuring section {section_index}/{section_count}: {draft.title}"
        _report_progress(
          "transform",
          struct_subphase,
          [struct_msg],
          section_progress=_section_progress(
            section_index, title=draft.title, status="generating", completed_sections=len(structured_sections)
          ),
        )

        try:
          structured = await structurer_agent.run(draft, ctx)

        except Exception as exc:
          # Fail fast on structurer errors to avoid returning partial lessons.
          structurer_model = _model_name(structurer_model_instance)
          _log_request_failure(
            logger=logger,
            logs=logs,
            agent="Structurer",
            provider=self._structurer_provider,
            model=structurer_model,
            prompt=None,
            response=None,
            error=exc,
          )
          _log_pipeline_snapshot(
            logger=logger,
            logs=logs,
            agent="Structurer",
            error=exc,
            lesson_plan=lesson_plan,
            draft_artifacts=draft_artifacts,
            structured_artifacts=structured_artifacts,
            repair_artifacts=repair_artifacts,
          )
          error_message = f"Structurer failed for section {section_index}/{section_count}: {exc}"
          logs.append(error_message)
          _report_progress("transform", struct_subphase, [error_message], advance=False)
          raise OrchestrationError(error_message, logs=list(logs)) from exc

        structured_artifacts.append(structured.model_dump(mode="python"))
        structured_section = await _process_structured_section(
          draft=draft, structured=structured, section_index=section_index
        )

        if structured_section is not None:
          structured_sections.append(structured_section)
          _report_progress(
            "transform",
            f"section_{section_index}_ready",
            [f"Section {section_index}/{section_count} ready."],
            advance=False,
            partial_json=_build_partial_lesson(structured_sections),
            section_progress=_section_progress(
              section_index, title=draft.title, status="completed", completed_sections=len(structured_sections)
            ),
          )

    _report_progress("transform", "stitch_sections", ["Stitching sections..."])
    stitch_log = "Stitching sections..."
    logs.append(stitch_log)
    logger.info(stitch_log)
    batch = StructuredSectionBatch(sections=structured_sections)

    try:
      stitch_result = await stitcher_agent.run(batch, ctx)
    except Exception as exc:
      # Fail fast on stitcher errors so the request closes with an error.
      stitch_model = _model_name(structurer_model_instance)
      _log_request_failure(
        logger=logger,
        logs=logs,
        agent="Stitcher",
        provider=self._structurer_provider,
        model=stitch_model,
        prompt=None,
        response=None,
        error=exc,
      )
      _log_pipeline_snapshot(
        logger=logger,
        logs=logs,
        agent="Stitcher",
        error=exc,
        lesson_plan=lesson_plan,
        draft_artifacts=draft_artifacts,
        structured_artifacts=structured_artifacts,
        repair_artifacts=repair_artifacts,
      )
      error_message = f"Stitcher failed: {exc}"
      logs.append(error_message)
      _report_progress("transform", "stitch_sections", [error_message], advance=False)
      raise OrchestrationError(error_message, logs=list(logs)) from exc

    lesson_json = stitch_result.lesson_json
    metadata = stitch_result.metadata or {}
    validation_errors = metadata.get("validation_errors") or None

    if validation_errors:
      # Treat stitcher validation errors as fatal to avoid returning invalid lessons.
      error_message = f"Stitcher validation failed: {validation_errors}"
      logs.append(error_message)
      logger.error("Stitcher validation failed: %s", validation_errors)
      _report_progress("transform", "stitch_sections", [error_message], advance=False)
      raise OrchestrationError(error_message, logs=list(logs))

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
    return OrchestrationResult(
      lesson_json=lesson_json,
      provider_a=self._gatherer_provider,
      model_a=gatherer_model,
      provider_b=self._structurer_provider,
      model_b=structurer_model,
      validation_errors=validation,
      logs=logs,
      usage=all_usage,
      total_cost=total_cost,
      artifacts=artifacts,
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


def _depth_profile(depth: str) -> int:
  """Map numeric depth to DLE labels and section counts for prompt rendering."""
  # Keep prompt depth labels aligned with the API depth tiers.
  mapping = {"highlights": 2, "detailed": 6, "training": 10}

  if depth.lower() in mapping:
    return mapping[depth.lower()]

  raise ValueError("Depth must be one of the following: Highlights, Detailed or Training.")


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


def _build_failure_snapshot(
  lesson_plan: LessonPlan | None,
  draft_artifacts: list[dict[str, Any]],
  structured_artifacts: list[dict[str, Any]],
  repair_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
  """Capture the newest artifacts so partial pipeline output is visible during failures."""
  # Surface the newest data only to keep logs readable while still debugging failures.
  plan_payload: dict[str, Any] | None = None

  if lesson_plan is not None:
    plan_payload = lesson_plan.model_dump(mode="python")

  snapshot = {
    "plan": plan_payload,
    "drafts_count": len(draft_artifacts),
    "latest_draft": draft_artifacts[-1] if draft_artifacts else None,
    "structured_count": len(structured_artifacts),
    "latest_structured": structured_artifacts[-1] if structured_artifacts else None,
    "repairs_count": len(repair_artifacts),
    "latest_repair": repair_artifacts[-1] if repair_artifacts else None,
  }
  return snapshot


def _log_pipeline_snapshot(
  *,
  logger: logging.Logger,
  logs: list[str] | None,
  agent: str,
  error: Exception,
  lesson_plan: LessonPlan | None,
  draft_artifacts: list[dict[str, Any]],
  structured_artifacts: list[dict[str, Any]],
  repair_artifacts: list[dict[str, Any]],
) -> None:
  """Log the latest available artifacts so failed pipelines retain context."""
  # Serialize a focused snapshot for operational debugging.
  snapshot = _build_failure_snapshot(
    lesson_plan=lesson_plan,
    draft_artifacts=draft_artifacts,
    structured_artifacts=structured_artifacts,
    repair_artifacts=repair_artifacts,
  )
  snapshot_json = json.dumps(snapshot, ensure_ascii=True)
  message = f"{agent} failure snapshot (error={error}): {snapshot_json}"

  if logs is not None:
    logs.append(message)

  logger.warning(message)


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
    raise ValueError("Depth must be Highlights, Detailed, Training") from exc
  if depth < 2:
    raise ValueError("Depth must be at least 2.")
  if depth > 10:
    raise ValueError("Depth exceeds the maximum of 10.")
  return depth
