"Orchestration for the multi-agent AI pipeline."

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.ai.agents import PlannerAgent, RepairerAgent, SectionBuilder, StitcherAgent
from app.ai.pipeline.contracts import GenerationRequest, JobContext, LessonPlan, RepairInput, SectionDraft, StructuredSection, StructuredSectionBatch
from app.ai.providers.base import AIModel
from app.ai.router import get_model_for_mode
from app.ai.utils.artifacts import build_failure_snapshot, build_partial_lesson
from app.ai.utils.cost import calculate_total_cost
from app.ai.utils.progress import SectionProgressUpdate, create_section_progress
from app.schema.service import SchemaService

OptStr = str | None
Msgs = list[str] | None
ProgressCallback = Callable[[str, OptStr, Msgs, bool, dict[str, Any] | None, Optional["SectionProgressUpdate"]], Awaitable[None]] | None
JobCreator = Callable[[str, dict[str, Any]], Awaitable[None]] | None
DEFAULT_MODEL = "gemini-2.5-pro"


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


@dataclass
class _OrchestrationContext:
  """Mutable state for the orchestration lifecycle."""

  job_context: JobContext
  progress_reporter: Callable[..., Awaitable[None]]
  logs: list[str] = field(default_factory=list)
  usage: list[dict[str, Any]] = field(default_factory=list)
  draft_artifacts: list[dict[str, Any]] = field(default_factory=list)
  structured_artifacts: list[dict[str, Any]] = field(default_factory=list)
  repair_artifacts: list[dict[str, Any]] = field(default_factory=list)
  structured_sections: list[StructuredSection] = field(default_factory=list)
  validation_errors: list[str] | None = None
  lesson_plan: LessonPlan | None = None
  topic: str = ""
  section_count: int = 0


@dataclass
class _AgentsBundle:
  """Group of agents and their models used in the pipeline."""

  planner: PlannerAgent
  section_builder: SectionBuilder
  repairer: RepairerAgent
  stitcher: StitcherAgent
  planner_model: AIModel
  section_builder_model: AIModel
  repairer_model: AIModel


class DylenOrchestrator:
  """Coordinates the section builder agent."""

  def __init__(
    self,
    *,
    section_builder_provider: str,
    section_builder_model: str | None,
    planner_provider: str,
    planner_model: str | None,
    repair_provider: str,
    repair_model: str | None,
    schema_version: str,
    fenster_technical_constraints: dict[str, Any] | None = None,
  ) -> None:
    self._section_builder_provider = section_builder_provider
    self._section_builder_model_name = section_builder_model
    self._planner_provider = planner_provider
    self._planner_model_name = planner_model
    self._repair_provider = repair_provider
    self._repair_model_name = repair_model
    self._schema_version = schema_version
    self._schema_service = SchemaService()
    self._fenster_technical_constraints = fenster_technical_constraints or {}

  async def generate_lesson(
    self,
    *,
    job_id: str | None = None,
    topic: str,
    details: str | None = None,
    outcomes: list[str] | None = None,
    blueprint: str | None = None,
    teaching_style: list[str] | None = None,
    learner_level: str | None = None,
    depth: str | None = None,
    widgets: list[str] | None = None,
    schema_version: str | None = None,
    section_builder_model: str | None = None,
    structured_output: bool = True,
    language: str | None = None,
    enable_repair: bool = True,
    progress_callback: ProgressCallback = None,
    section_filter: set[int] | None = None,
    job_creator: JobCreator = None,
    job_metadata: dict[str, Any] | None = None,
  ) -> OrchestrationResult:
    """Run the pipeline and return lesson JSON."""
    logger = logging.getLogger(__name__)

    async def _report_progress(phase_name: str, subphase: OptStr, messages: Msgs = None, advance: bool = True, partial_json: dict[str, Any] | None = None, section_progress: SectionProgressUpdate | None = None) -> None:
      if progress_callback:
        await progress_callback(phase_name, subphase, messages, advance, partial_json, section_progress)

    # Setup context and request
    request_payload = {
      "topic": topic,
      "prompt": details,
      "outcomes": outcomes,
      "depth": depth,
      "section_count": _depth_profile(depth),
      "blueprint": blueprint,
      "teaching_style": teaching_style,
      "learner_level": learner_level,
      "language": language,
      "widgets": widgets,
      "constraints": None,
    }
    request = GenerationRequest(**request_payload)

    schema_ver = schema_version or self._schema_version
    # Merge caller-provided metadata so agents can access user context.
    meta = {"schema_version": schema_ver, "structured_output": structured_output}
    if job_metadata:
      meta.update(job_metadata)
    # Fall back to a sentinel job id when none is provided.
    resolved_job_id = job_id or "unknown"
    job_ctx = JobContext(job_id=resolved_job_id, created_at=datetime.utcnow(), provider="multi", model="multi", request=request, metadata=meta)

    ctx = _OrchestrationContext(job_context=job_ctx, progress_reporter=_report_progress, topic=topic)

    # Initial logging
    self._log_initial_config(logger, ctx, section_builder_model)

    # Initialize agents
    agents = self._initialize_agents(ctx.usage.append, section_builder_model)

    # Plan
    await self._run_planning_phase(ctx, agents, logger, job_creator)

    # Generate Sections
    await self._run_section_generation_phase(ctx, agents, logger, section_filter, enable_repair, job_creator)

    # Stitch
    lesson_json = await self._run_stitching_phase(ctx, agents, logger)

    # Finalize
    total_cost = calculate_total_cost(ctx.usage)
    artifacts = {"plan": ctx.lesson_plan.model_dump(mode="python") if ctx.lesson_plan else None, "drafts": ctx.draft_artifacts, "structured_sections": ctx.structured_artifacts, "repairs": ctx.repair_artifacts, "final_lesson": lesson_json}

    log_msg = "Generation pipeline complete"
    ctx.logs.append(log_msg)
    logger.info(log_msg)

    return OrchestrationResult(
      lesson_json=lesson_json,
      provider_a=self._planner_provider,
      model_a=_model_name(agents.planner_model),
      provider_b=self._section_builder_provider,
      model_b=_model_name(agents.section_builder_model),
      validation_errors=ctx.validation_errors,
      logs=ctx.logs,
      usage=ctx.usage,
      total_cost=total_cost,
      artifacts=artifacts,
    )

  def _log_initial_config(self, logger: logging.Logger, ctx: _OrchestrationContext, section_builder_model_override: str | None) -> None:
    topic_preview = ctx.topic[:50] + "..." if len(ctx.topic) >= 50 else ctx.topic
    msgs = [f"Starting generation for topic: '{topic_preview}'"]

    section_builder_model = section_builder_model_override or self._section_builder_model_name
    msgs.append(f"SectionBuilder: {self._section_builder_provider}/{section_builder_model or 'default'}")

    planner_model = self._planner_model_name
    msgs.append(f"Planner: {self._planner_provider}/{planner_model or 'default'}")

    for msg in msgs:
      ctx.logs.append(msg)
      logger.info(msg)

  def _initialize_agents(self, usage_sink: Callable[[dict[str, Any]], None], section_builder_model_override: str | None) -> _AgentsBundle:
    section_builder_model_name = section_builder_model_override or self._section_builder_model_name
    planner_model_name = self._planner_model_name

    # Use default if None
    section_builder_model_name = section_builder_model_name or DEFAULT_MODEL
    planner_model_name = planner_model_name or DEFAULT_MODEL

    section_builder_model_instance = get_model_for_mode(self._section_builder_provider, section_builder_model_name, agent="section_builder")
    planner_model_instance = get_model_for_mode(self._planner_provider, planner_model_name, agent="planner")
    repairer_model_instance = get_model_for_mode(self._repair_provider, self._repair_model_name or DEFAULT_MODEL, agent="repairer")
    # Stitcher uses section builder model implicitly or can be separate. Using section builder model for consistency if nothing else specified, but stitcher agent usually just needs a robust model.
    # The original code used structurer model for stitcher. Let's use section builder model.
    stitcher_model_instance = section_builder_model_instance

    schema = self._schema_service

    planner_agent = PlannerAgent(model=planner_model_instance, prov=self._planner_provider, schema=schema, use=usage_sink)
    section_builder_agent = SectionBuilder(model=section_builder_model_instance, prov=self._section_builder_provider, schema=schema, use=usage_sink)
    repairer_agent = RepairerAgent(model=repairer_model_instance, prov=self._repair_provider, schema=schema, use=usage_sink)
    stitcher_agent = StitcherAgent(model=stitcher_model_instance, prov=self._section_builder_provider, schema=schema, use=usage_sink)

    return _AgentsBundle(
      planner=planner_agent, section_builder=section_builder_agent, repairer=repairer_agent, stitcher=stitcher_agent, planner_model=planner_model_instance, section_builder_model=section_builder_model_instance, repairer_model=repairer_model_instance
    )

  async def _run_planning_phase(self, ctx: _OrchestrationContext, agents: _AgentsBundle, logger: logging.Logger, job_creator: JobCreator) -> None:
    await ctx.progress_reporter("plan", "planner_start", ["Planning lesson sections..."])
    try:
      ctx.lesson_plan = await agents.planner.run(ctx.job_context.request, ctx.job_context)
      ctx.section_count = len(ctx.lesson_plan.sections)
    except Exception as exc:
      _handle_agent_failure(ctx, logger, "Planner", self._planner_provider, agents.planner_model, exc)

    await ctx.progress_reporter("plan", "planner_complete", ["Lesson plan ready."])

    if job_creator and ctx.lesson_plan:
      await self._create_widget_jobs(ctx.lesson_plan, ctx.job_context, job_creator, logger)

  async def _create_widget_jobs(self, plan: LessonPlan, job_context: JobContext, job_creator: Callable[[str, dict[str, Any]], Awaitable[None]], logger: logging.Logger) -> None:
    for section in plan.sections:
      for subsection in section.subsections:
        for widget_context in subsection.planned_widgets:
          payload = {
            "lesson_id": "pending",
            "concept_context": f"Widget for: {widget_context}. Context: {subsection.title} in {section.title}. Topic: {job_context.request.topic}",
            "target_audience": job_context.request.learner_level or "Student",
            "technical_constraints": self._fenster_technical_constraints,
          }
          await job_creator("fenster_builder", payload)
          logger.info("Created fenster_builder job for widget: %s", widget_context)

  async def _run_section_generation_phase(self, ctx: _OrchestrationContext, agents: _AgentsBundle, logger: logging.Logger, section_filter: set[int] | None, enable_repair: bool, job_creator: JobCreator) -> None:
    assert ctx.lesson_plan is not None

    sections: dict[int, SectionDraft] = {}
    target_sections = set(section_filter) if section_filter else None
    target_section_count = len(target_sections) if target_sections is not None else ctx.section_count

    if not enable_repair:
      msg = "Repair is disabled; pipeline will stop on invalid sections."
      ctx.logs.append(msg)
      logger.info(msg)

    for plan_section in ctx.lesson_plan.sections:
      section_index = plan_section.section_number
      if target_sections is not None and section_index not in target_sections:
        continue

      await self._generate_section(ctx, agents, logger, plan_section, sections, enable_repair, job_creator)

    # Validation of collected sections
    if len(sections) < target_section_count:
      missing = sorted(set(range(1, ctx.section_count + 1)) - set(sections.keys()))
      if target_sections is not None:
        missing = sorted(set(target_sections) - set(sections.keys()))

      error_msg = f"Missing extracted sections: {missing}"
      ctx.logs.append(error_msg)
      logger.error("Missing extracted sections: %s", missing)
      await ctx.progress_reporter("collect", "missing_sections", [error_msg], advance=False)
      raise OrchestrationError(error_msg, logs=list(ctx.logs))

  async def _generate_section(self, ctx: _OrchestrationContext, agents: _AgentsBundle, logger: logging.Logger, plan_section: Any, sections: dict[int, SectionDraft], enable_repair: bool, job_creator: JobCreator) -> None:
    section_index = plan_section.section_number

    subphase = f"build_section_{section_index}_of_{ctx.section_count}"
    msg = f"Building section {section_index}/{ctx.section_count}: {plan_section.title}"
    await ctx.progress_reporter("transform", subphase, [msg], section_progress=create_section_progress(section_index, title=plan_section.title, status="generating", completed_sections=len(ctx.structured_sections)))

    try:
      structured = await agents.section_builder.run(plan_section, ctx.job_context)
    except Exception as exc:
      _handle_agent_failure(ctx, logger, "SectionBuilder", self._section_builder_provider, agents.section_builder_model, exc)

    if section_index < 1 or section_index > ctx.section_count:
      _handle_out_of_range(ctx, logger, subphase, section_index)

    draft = SectionDraft(section_number=section_index, title=plan_section.title, plan_section=plan_section, raw_text="SectionBuilder output.", extracted_parts=None)
    sections[section_index] = draft
    ctx.draft_artifacts.append(draft.model_dump(mode="python"))
    ctx.structured_artifacts.append(structured.model_dump(mode="python"))

    await self._validate_and_repair_section(ctx, agents, logger, draft, structured, section_index, enable_repair, job_creator)

  async def _validate_and_repair_section(self, ctx: _OrchestrationContext, agents: _AgentsBundle, logger: logging.Logger, draft: SectionDraft, structured: StructuredSection, section_index: int, enable_repair: bool, job_creator: JobCreator) -> None:
    if structured.validation_errors and not enable_repair:
      ctx.validation_errors = structured.validation_errors
      msg = f"Section {section_index} failed validation: {structured.validation_errors}"
      ctx.logs.append(msg)
      logger.error("Section %s failed validation: %s", section_index, structured.validation_errors)
      await ctx.progress_reporter("transform", f"validate_section_{section_index}_of_{ctx.section_count}", [msg], advance=False)
      raise OrchestrationError(msg, logs=list(ctx.logs))

    section_json = structured.payload

    if enable_repair and structured.validation_errors:
      await ctx.progress_reporter(
        "transform",
        f"repair_section_{section_index}_of_{ctx.section_count}",
        [f"Retrying section {section_index}/{ctx.section_count} after validation failure."],
        advance=False,
        partial_json=build_partial_lesson(ctx.structured_sections, ctx.topic),
        section_progress=create_section_progress(section_index, title=draft.title, status="retrying", retry_count=1, completed_sections=len(ctx.structured_sections)),
      )

      repair_input = RepairInput(section=draft, structured=structured)
      try:
        repair_result = await agents.repairer.run(repair_input, ctx.job_context)
      except Exception as exc:
        _handle_agent_failure(ctx, logger, "Repairer", self._repair_provider, agents.repairer_model, exc)

      ctx.repair_artifacts.append(repair_result.model_dump(mode="python"))
      if repair_result.errors:
        ctx.validation_errors = repair_result.errors
        msg = f"Section {section_index} failed repair validation: {repair_result.errors}"
        ctx.logs.append(msg)
        logger.error("Section %s failed repair validation: %s", section_index, repair_result.errors)
        await ctx.progress_reporter("transform", f"repair_section_{section_index}_of_{ctx.section_count}", [msg], advance=False)
        raise OrchestrationError(msg, logs=list(ctx.logs))

      section_json = repair_result.fixed_json

    await ctx.progress_reporter("transform", f"validate_section_{section_index}_of_{ctx.section_count}", [f"Section {section_index} validated."])
    final_section = StructuredSection(section_number=section_index, json=section_json, validation_errors=[])
    ctx.structured_sections.append(final_section)

    if job_creator:
      payload = {"section_index": section_index, "topic": ctx.topic, "section_data": section_json, "learning_data_points": section_json.get("learning_data_points", [])}
      await job_creator("coach", payload)
      logger.info("Created coach job for section %s", section_index)

    await ctx.progress_reporter(
      "transform",
      f"section_{section_index}_ready",
      [f"Section {section_index}/{ctx.section_count} ready."],
      advance=False,
      partial_json=build_partial_lesson(ctx.structured_sections, ctx.topic),
      section_progress=create_section_progress(section_index, title=draft.title, status="completed", completed_sections=len(ctx.structured_sections)),
    )

  async def _run_stitching_phase(self, ctx: _OrchestrationContext, agents: _AgentsBundle, logger: logging.Logger) -> dict[str, Any]:
    await ctx.progress_reporter("transform", "stitch_sections", ["Stitching sections..."])
    log_msg = "Stitching sections..."
    ctx.logs.append(log_msg)
    logger.info(log_msg)

    batch = StructuredSectionBatch(sections=ctx.structured_sections)
    try:
      stitch_result = await agents.stitcher.run(batch, ctx.job_context)
    except Exception as exc:
      _handle_agent_failure(ctx, logger, "Stitcher", self._section_builder_provider, agents.section_builder_model, exc)

    lesson_json = stitch_result.lesson_json
    metadata = stitch_result.metadata or {}
    val_errors = metadata.get("validation_errors") or None

    if val_errors:
      msg = f"Stitcher validation failed: {val_errors}"
      ctx.logs.append(msg)
      logger.error("Stitcher validation failed: %s", val_errors)
      await ctx.progress_reporter("transform", "stitch_sections", [msg], advance=False)
      raise OrchestrationError(msg, logs=list(ctx.logs))

    return lesson_json


def _handle_agent_failure(ctx: _OrchestrationContext, logger: logging.Logger, agent_name: str, provider: str, model: AIModel, error: Exception) -> None:
  model_name = _model_name(model)
  _log_request_failure(logger=logger, logs=ctx.logs, agent=agent_name, provider=provider, model=model_name, prompt=None, response=None, error=error)
  _log_pipeline_snapshot(logger=logger, logs=ctx.logs, agent=agent_name, error=error, lesson_plan=ctx.lesson_plan, draft_artifacts=ctx.draft_artifacts, structured_artifacts=ctx.structured_artifacts, repair_artifacts=ctx.repair_artifacts)
  error_message = f"{agent_name} failed: {error}"
  ctx.logs.append(error_message)
  raise OrchestrationError(error_message, logs=list(ctx.logs)) from error


def _handle_out_of_range(ctx: _OrchestrationContext, logger: logging.Logger, subphase: str, section_index: int) -> None:
  error_message = f"Received out-of-range section index {section_index}."
  ctx.logs.append(error_message)
  logger.error("Out-of-range section index %s.", section_index)
  raise OrchestrationError(error_message, logs=list(ctx.logs))


def _depth_profile(depth: str) -> int:
  """Map numeric depth to Dylen labels and section counts for prompt rendering."""
  mapping = {"highlights": 2, "detailed": 6, "training": 10}
  if depth.lower() in mapping:
    return mapping[depth.lower()]
  raise ValueError("Depth must be one of the following: Highlights, Detailed or Training.")


def _log_request_failure(*, logger: logging.Logger, logs: list[str] | None, agent: str, provider: str, model: str, prompt: str | None, response: str | None, error: Exception) -> None:
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


def _log_pipeline_snapshot(
  *, logger: logging.Logger, logs: list[str] | None, agent: str, error: Exception, lesson_plan: LessonPlan | None, draft_artifacts: list[dict[str, Any]], structured_artifacts: list[dict[str, Any]], repair_artifacts: list[dict[str, Any]]
) -> None:
  snapshot = build_failure_snapshot(lesson_plan=lesson_plan, draft_artifacts=draft_artifacts, structured_artifacts=structured_artifacts, repair_artifacts=repair_artifacts)
  snapshot_json = json.dumps(snapshot, ensure_ascii=True)
  message = f"{agent} failure snapshot (error={error}): {snapshot_json}"
  if logs is not None:
    logs.append(message)
  logger.warning(message)


def _model_name(model: AIModel) -> str:
  return getattr(model, "name", "unknown")
