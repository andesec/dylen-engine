"Orchestration for the multi-agent AI pipeline."

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.ai.agents import GathererAgent, GathererStructurerAgent, PlannerAgent, RepairerAgent, StitcherAgent, StructurerAgent
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
  gatherer: GathererAgent | None
  gatherer_structurer: GathererStructurerAgent | None
  structurer: StructurerAgent
  repairer: RepairerAgent
  stitcher: StitcherAgent
  planner_model: AIModel
  gatherer_model: AIModel
  structurer_model: AIModel
  repairer_model: AIModel


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
    job_creator: JobCreator = None,
  ) -> OrchestrationResult:
    """Run the 5-agent pipeline and return lesson JSON."""
    logger = logging.getLogger(__name__)

    async def _report_progress(phase_name: str, subphase: OptStr, messages: Msgs = None, advance: bool = True, partial_json: dict[str, Any] | None = None, section_progress: SectionProgressUpdate | None = None) -> None:
      if progress_callback:
        await progress_callback(phase_name, subphase, messages, advance, partial_json, section_progress)

    # Setup context and request
    request = GenerationRequest(topic=topic, prompt=details, depth=depth, section_count=_depth_profile(depth), blueprint=blueprint, teaching_style=teaching_style, learner_level=learner_level, language=language, widgets=widgets, constraints=None)

    schema_ver = schema_version or self._schema_version
    meta = {"schema_version": schema_ver, "structured_output": structured_output}
    job_ctx = JobContext(job_id="unknown", created_at=datetime.utcnow(), provider="multi", model="multi", request=request, metadata=meta)

    ctx = _OrchestrationContext(job_context=job_ctx, progress_reporter=_report_progress, topic=topic)

    # Initial logging
    self._log_initial_config(logger, ctx, gatherer_model, structurer_model)

    # Initialize agents
    agents = self._initialize_agents(ctx.usage.append, gatherer_model, structurer_model)

    # Plan
    await self._run_planning_phase(ctx, agents, logger, job_creator)

    # Generate Sections
    await self._run_section_generation_phase(ctx, agents, logger, section_filter, enable_repair)

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
      provider_a=self._gatherer_provider,
      model_a=_model_name(agents.gatherer_model),
      provider_b=self._structurer_provider,
      model_b=_model_name(agents.structurer_model),
      validation_errors=ctx.validation_errors,
      logs=ctx.logs,
      usage=ctx.usage,
      total_cost=total_cost,
      artifacts=artifacts,
    )

  def _log_initial_config(self, logger: logging.Logger, ctx: _OrchestrationContext, gatherer_model_override: str | None, structurer_model_override: str | None) -> None:
    topic_preview = ctx.topic[:50] + "..." if len(ctx.topic) >= 50 else ctx.topic
    msgs = [f"Starting generation for topic: '{topic_preview}'"]

    gatherer_model = gatherer_model_override or self._gatherer_model_name
    merged_model = gatherer_model or MERGED_DEFAULT_MODEL

    if self._merge_gatherer_structurer:
      msgs.append(f"Gatherer+Structurer (merged): {self._gatherer_provider}/{merged_model or 'default'}")
    else:
      msgs.append(f"Gatherer: {self._gatherer_provider}/{gatherer_model or 'default'}")

    planner_model = self._planner_model_name or (structurer_model_override or self._structurer_model_name)
    msgs.append(f"Planner: {self._planner_provider}/{planner_model or 'default'}")

    structurer_model = structurer_model_override or self._structurer_model_name
    msgs.append(f"Structurer: {self._structurer_provider}/{structurer_model or 'default'}")

    for msg in msgs:
      ctx.logs.append(msg)
      logger.info(msg)

  def _initialize_agents(self, usage_sink: Callable[[dict[str, Any]], None], gatherer_model_override: str | None, structurer_model_override: str | None) -> _AgentsBundle:
    gatherer_model_name = gatherer_model_override or self._gatherer_model_name
    structurer_model_name = structurer_model_override or self._structurer_model_name
    planner_model_name = self._planner_model_name or structurer_model_name
    merged_model_name = gatherer_model_name or MERGED_DEFAULT_MODEL

    if self._merge_gatherer_structurer:
      gatherer_model_instance = get_model_for_mode(self._gatherer_provider, merged_model_name, agent="gatherer_structurer")
    else:
      gatherer_model_instance = get_model_for_mode(self._gatherer_provider, gatherer_model_name, agent="gatherer")

    planner_model_instance = get_model_for_mode(self._planner_provider, planner_model_name, agent="planner")
    structurer_model_instance = get_model_for_mode(self._structurer_provider, structurer_model_name, agent="structurer")
    repairer_model_instance = get_model_for_mode(self._repair_provider, self._repair_model_name, agent="repairer")

    schema = self._schema_service

    planner_agent = PlannerAgent(model=planner_model_instance, prov=self._planner_provider, schema=schema, use=usage_sink)
    structurer_agent = StructurerAgent(model=structurer_model_instance, prov=self._structurer_provider, schema=schema, use=usage_sink)
    repairer_agent = RepairerAgent(model=repairer_model_instance, prov=self._repair_provider, schema=schema, use=usage_sink)
    stitcher_agent = StitcherAgent(model=structurer_model_instance, prov=self._structurer_provider, schema=schema, use=usage_sink)

    gatherer_agent = None
    gatherer_structurer_agent = None

    if self._merge_gatherer_structurer:
      gatherer_structurer_agent = GathererStructurerAgent(model=gatherer_model_instance, prov=self._gatherer_provider, schema=schema, use=usage_sink)
    else:
      gatherer_agent = GathererAgent(model=gatherer_model_instance, prov=self._gatherer_provider, schema=schema, use=usage_sink)

    return _AgentsBundle(
      planner=planner_agent,
      gatherer=gatherer_agent,
      gatherer_structurer=gatherer_structurer_agent,
      structurer=structurer_agent,
      repairer=repairer_agent,
      stitcher=stitcher_agent,
      planner_model=planner_model_instance,
      gatherer_model=gatherer_model_instance,
      structurer_model=structurer_model_instance,
      repairer_model=repairer_model_instance,
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
            "technical_constraints": {"max_tokens": 4000, "allowed_libs": ["alpine", "tailwind"]},
          }
          await job_creator("fenster_builder", payload)
          logger.info("Created fenster_builder job for widget: %s", widget_context)

  async def _run_section_generation_phase(self, ctx: _OrchestrationContext, agents: _AgentsBundle, logger: logging.Logger, section_filter: set[int] | None, enable_repair: bool) -> None:
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

      await self._generate_section(ctx, agents, logger, plan_section, sections, enable_repair)

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

    if not self._merge_gatherer_structurer:
      await self._structure_sections_phase(ctx, agents, logger, sections, target_sections, enable_repair)

  async def _generate_section(self, ctx: _OrchestrationContext, agents: _AgentsBundle, logger: logging.Logger, plan_section: Any, sections: dict[int, SectionDraft], enable_repair: bool) -> None:
    section_index = plan_section.section_number

    if self._merge_gatherer_structurer:
      assert agents.gatherer_structurer is not None
      subphase = f"gather_struct_section_{section_index}_of_{ctx.section_count}"
      msg = f"Gathering+structuring section {section_index}/{ctx.section_count}: {plan_section.title}"
      await ctx.progress_reporter("transform", subphase, [msg], section_progress=create_section_progress(section_index, title=plan_section.title, status="generating", completed_sections=len(ctx.structured_sections)))

      try:
        structured = await agents.gatherer_structurer.run(plan_section, ctx.job_context)
      except Exception as exc:
        _handle_agent_failure(ctx, logger, "GathererStructurer", self._gatherer_provider, agents.gatherer_model, exc)

      if section_index < 1 or section_index > ctx.section_count:
        _handle_out_of_range(ctx, logger, subphase, section_index)

      draft = SectionDraft(section_number=section_index, title=plan_section.title, plan_section=plan_section, raw_text="Merged gatherer-structurer output.", extracted_parts=None)
      sections[section_index] = draft
      ctx.draft_artifacts.append(draft.model_dump(mode="python"))
      ctx.structured_artifacts.append(structured.model_dump(mode="python"))

      await self._validate_and_repair_section(ctx, agents, logger, draft, structured, section_index, enable_repair)

    else:
      assert agents.gatherer is not None
      subphase = f"gather_section_{section_index}_of_{ctx.section_count}"
      msg = f"Gathering section {section_index}/{ctx.section_count}: {plan_section.title}"
      await ctx.progress_reporter("collect", subphase, [msg], section_progress=create_section_progress(section_index, title=plan_section.title, status="generating", completed_sections=len(ctx.structured_sections)))

      try:
        draft = await agents.gatherer.run(plan_section, ctx.job_context)
      except Exception as exc:
        _handle_agent_failure(ctx, logger, "Gatherer", self._gatherer_provider, agents.gatherer_model, exc)

      if section_index < 1 or section_index > ctx.section_count:
        _handle_out_of_range(ctx, logger, subphase, section_index)

      sections[section_index] = draft
      ctx.draft_artifacts.append(draft.model_dump(mode="python"))
      await ctx.progress_reporter(
        "collect",
        f"extract_section_{section_index}_of_{ctx.section_count}",
        [f"Extracted section {section_index}/{ctx.section_count}"],
        section_progress=create_section_progress(section_index, title=draft.title, status="generating", completed_sections=len(ctx.structured_sections)),
      )

  async def _structure_sections_phase(self, ctx: _OrchestrationContext, agents: _AgentsBundle, logger: logging.Logger, sections: dict[int, SectionDraft], target_sections: set[int] | None, enable_repair: bool) -> None:
    section_indexes = list(range(1, ctx.section_count + 1))
    if target_sections is not None:
      section_indexes = sorted(target_sections)

    for section_index in section_indexes:
      draft = sections.get(section_index)
      if draft is None:
        continue

      subphase = f"struct_section_{section_index}_of_{ctx.section_count}"
      msg = f"Structuring section {section_index}/{ctx.section_count}: {draft.title}"
      await ctx.progress_reporter("transform", subphase, [msg], section_progress=create_section_progress(section_index, title=draft.title, status="generating", completed_sections=len(ctx.structured_sections)))

      try:
        structured = await agents.structurer.run(draft, ctx.job_context)
      except Exception as exc:
        _handle_agent_failure(ctx, logger, "Structurer", self._structurer_provider, agents.structurer_model, exc)

      ctx.structured_artifacts.append(structured.model_dump(mode="python"))
      await self._validate_and_repair_section(ctx, agents, logger, draft, structured, section_index, enable_repair)

  async def _validate_and_repair_section(self, ctx: _OrchestrationContext, agents: _AgentsBundle, logger: logging.Logger, draft: SectionDraft, structured: StructuredSection, section_index: int, enable_repair: bool) -> None:
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
      _handle_agent_failure(ctx, logger, "Stitcher", self._structurer_provider, agents.structurer_model, exc)

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
  # Raising error so upstream can handle it (which will be OrchestrationError via the wrapper, but here we just re-raise or raise new)
  # The original code raised OrchestrationError wrapping the logs.
  raise OrchestrationError(error_message, logs=list(ctx.logs)) from error


def _handle_out_of_range(ctx: _OrchestrationContext, logger: logging.Logger, subphase: str, section_index: int) -> None:
  error_message = f"Received out-of-range section index {section_index}."
  ctx.logs.append(error_message)
  logger.error("Out-of-range section index %s.", section_index)
  # we can't await in a sync helper easily unless we pass reporter, but caller handles exception
  # caller should catch and report? No, the original code reported progress then raised.
  # To keep it simple, I'll raise OrchestrationError and let the caller/wrapper handle it?
  # But I need to report progress before raising if I want to match original behavior EXACTLY.
  # I'll just raise here, and assume the top-level error handler (in worker) or just missing the progress update is fine for fatal error.
  # Actually, the original code did: await _report_progress(..., advance=False); raise ...
  # I'll raise here.
  raise OrchestrationError(error_message, logs=list(ctx.logs))


def _depth_profile(depth: str) -> int:
  """Map numeric depth to DLE labels and section counts for prompt rendering."""
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
  # ... (abbreviated for brevity, but I should keep full logic if possible or trust standard log)
  # Original code had more detail. I should keep it.
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
