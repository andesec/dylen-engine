"""Background processor for queued lesson generation jobs."""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.ai.agents.fenster_builder import FensterBuilderAgent
from app.ai.agents.illustration import IllustrationAgent
from app.ai.agents.planner import PlannerAgent
from app.ai.agents.repairer import RepairerAgent
from app.ai.agents.section_builder import SectionBuilder
from app.ai.agents.tutor import TutorAgent
from app.ai.pipeline.contracts import GenerationRequest, JobContext, PlanSection, RepairInput, SectionDraft
from app.ai.pipeline.lesson_requests import GenerateLessonRequestStruct
from app.ai.router import get_model_for_mode
from app.ai.utils.cost import calculate_total_cost
from app.config import Settings
from app.core.database import get_session_factory
from app.jobs.dispatch import JobProcessorHandler, JobProcessorRegistry
from app.jobs.dispatch import process_job as dispatch_process_job
from app.jobs.models import JobRecord
from app.jobs.progress import JobProgressTracker
from app.notifications.factory import build_notification_service
from app.schema.data_transfer import DataTransferRun
from app.schema.fenster import FensterWidget, FensterWidgetType
from app.schema.illustrations import Illustration
from app.schema.lesson_requests import LessonRequest
from app.schema.lessons import Lesson, Section, Subsection, SubsectionWidget
from app.schema.quotas import QuotaPeriod
from app.schema.service import SchemaService
from app.services.data_transfer_bundle import execute_export_run, execute_hydrate_run
from app.services.feature_flags import resolve_feature_flag_decision
from app.services.llm_pricing import load_pricing_table
from app.services.maintenance import archive_old_lessons
from app.services.quota_buckets import QuotaExceededError, get_quota_snapshot
from app.services.runtime_config import get_fenster_model, get_illustration_model, get_planner_model, get_repair_model, get_section_builder_model, get_tutor_model, resolve_effective_runtime_config
from app.services.section_shorthand import build_section_shorthand_content
from app.services.storage_client import build_storage_client
from app.services.tasks.factory import get_task_enqueuer
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.storage.factory import _get_repo
from app.storage.jobs_repo import JobsRepository
from app.storage.lessons_repo import LessonRecord
from app.utils.compression import compress_html
from app.utils.ids import generate_lesson_id, generate_nanoid


class JobProcessor:
  """Coordinates execution of queued jobs."""

  def __init__(self, *, jobs_repo: JobsRepository, settings: Settings, registry: JobProcessorRegistry | None = None) -> None:
    self._jobs_repo = jobs_repo
    self._settings = settings
    self._logger = logging.getLogger(__name__)
    self._registry = registry or self._build_default_registry()

  def _build_default_registry(self) -> JobProcessorRegistry:
    """Build the default target-agent handler registry."""

    class _MethodHandler:
      """Adapter that exposes worker coroutine methods as DI handlers."""

      def __init__(self, method: Callable[[JobRecord], Awaitable[JobRecord | None]]) -> None:
        self._method = method

      async def process(self, job: JobRecord) -> JobRecord | None:
        return await self._method(job)

    handlers: dict[str, JobProcessorHandler] = {
      "planner": _MethodHandler(self._process_planner_job),
      "section_builder": _MethodHandler(self._process_section_builder_job),
      "fenster_builder": _MethodHandler(self._process_fenster_build),
      "tutor": _MethodHandler(self._process_tutor_job),
      "illustration": _MethodHandler(self._process_illustration_job),
      "maintenance": _MethodHandler(self._process_maintenance_job),
    }
    return JobProcessorRegistry(handlers)

  async def process_job(self, job: JobRecord) -> JobRecord | None:
    """Execute a single queued job, routing by type."""
    if job.status != "queued":
      return job
    target_agent = str(job.target_agent or "").strip()
    if target_agent == "lesson":
      target_agent = "planner"
    if target_agent == "":
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=list(job.logs or []) + ["Missing target_agent on queued job."], error_json={"message": "Missing target_agent on queued job."})
      return None
    await self._jobs_repo.update_job(job.job_id, status="running")
    try:
      result = await dispatch_process_job(job, target_agent, self._registry, self._jobs_repo, get_task_enqueuer(self._settings), None, self._settings)
      return result.record
    except Exception as exc:  # noqa: BLE001
      self._logger.error("Job processor dispatch failed for job %s", job.job_id, exc_info=True)
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=list(job.logs or []) + [f"Dispatch failed: {exc}"], error_json={"message": str(exc)})
      return None

  async def _create_child_job(self, *, parent_job: JobRecord, target_agent: str, payload: dict[str, Any], lesson_id: str | None, section_id: int | None, job_kind: str | None = None) -> JobRecord | None:
    """Create and enqueue a child job from a parent job."""
    if not await self._quota_available_for_target(user_id=parent_job.user_id, target_agent=target_agent):
      raise QuotaExceededError(f"{target_agent} quota unavailable")
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    child_job_id = str(uuid.uuid4())
    request_payload = {"payload": payload, "_meta": {"parent_job_id": parent_job.job_id}}

    child_record = JobRecord(
      job_id=child_job_id,
      root_job_id=str(parent_job.root_job_id or parent_job.job_id),
      user_id=parent_job.user_id,
      job_kind=(job_kind or parent_job.job_kind),
      request=request_payload,
      status="queued",
      parent_job_id=parent_job.job_id,
      lesson_id=lesson_id,
      section_id=section_id,
      target_agent=target_agent,
      phase="queued",
      created_at=timestamp,
      updated_at=timestamp,
      expected_sections=0,
      completed_sections=0,
      completed_section_indexes=[],
      retry_count=0,
      max_retries=0,
      logs=[],
      progress=0.0,
      ttl=parent_job.ttl,
      idempotency_key=f"{child_job_id}:{target_agent}",
    )
    await self._jobs_repo.create_job(child_record)
    checkpoint_section_index: int | None = None
    if "section_index" in payload:
      try:
        checkpoint_section_index = int(payload.get("section_index") or 0)
      except (TypeError, ValueError):
        checkpoint_section_index = None
    if checkpoint_section_index is None and "section_number" in payload:
      try:
        checkpoint_section_index = int(payload.get("section_number") or 0)
      except (TypeError, ValueError):
        checkpoint_section_index = None
    await self._jobs_repo.upsert_checkpoint(
      job_id=child_record.job_id, stage=target_agent, section_index=checkpoint_section_index if checkpoint_section_index and checkpoint_section_index > 0 else None, state="pending", artifact_refs_json={"lesson_id": lesson_id, "section_id": section_id}
    )
    enqueuer = get_task_enqueuer(self._settings)
    try:
      await enqueuer.enqueue(child_job_id, {})
    except Exception as exc:  # noqa: BLE001
      await self._jobs_repo.update_job(child_job_id, status="error", phase="failed", progress=100.0, logs=["Enqueue failed: CHILD_TASK_ENQUEUE_FAILED"], error_json={"message": str(exc), "code": "CHILD_TASK_ENQUEUE_FAILED"})
      await self._jobs_repo.upsert_checkpoint(
        job_id=child_job_id,
        stage=target_agent,
        section_index=checkpoint_section_index if checkpoint_section_index and checkpoint_section_index > 0 else None,
        state="error",
        artifact_refs_json={"lesson_id": lesson_id, "section_id": section_id},
        attempt_count=1,
        last_error=str(exc),
      )
      await self._jobs_repo.update_job(parent_job.job_id, logs=list(parent_job.logs or []) + [f"Failed to enqueue child job {child_job_id}."])
      await _notify_child_job_failed(settings=self._settings, parent_job=parent_job, child_job_id=child_job_id)
      return None
    return child_record

  async def _quota_available_for_target(self, *, user_id: str | None, target_agent: str) -> bool:
    """Check whether a child job target has available quota for the current user."""
    metric_map: dict[str, tuple[str, str, QuotaPeriod]] = {
      "section_builder": ("limits.sections_per_month", "section.generate", QuotaPeriod.MONTH),
      "tutor": ("limits.tutor_sections_per_month", "tutor.generate", QuotaPeriod.MONTH),
      "fenster_builder": ("limits.fenster_widgets_per_month", "fenster.widget.generate", QuotaPeriod.MONTH),
      "illustration": ("limits.image_generations_per_month", "image.generate", QuotaPeriod.MONTH),
      "planner": ("limits.lessons_per_week", "lesson.generate", QuotaPeriod.WEEK),
      "writing": ("limits.writing_checks_per_month", "writing.check", QuotaPeriod.MONTH),
    }
    config = metric_map.get(target_agent)
    if config is None:
      return True
    if user_id is None:
      return False
    session_factory = get_session_factory()
    if session_factory is None:
      return False
    try:
      parsed_user_id = uuid.UUID(str(user_id))
    except ValueError:
      return False
    limit_key, metric_key, period = config
    try:
      async with session_factory() as session:
        user = await get_user_by_id(session, parsed_user_id)
        if user is None:
          return False
        tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
        runtime_config = await resolve_effective_runtime_config(session, settings=self._settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
        limit = int(runtime_config.get(limit_key) or 0)
        if limit <= 0:
          return False
        snapshot = await get_quota_snapshot(session, user_id=user.id, metric_key=metric_key, period=period, limit=limit)
        return snapshot.remaining > 0
    except Exception:  # noqa: BLE001
      self._logger.error("Quota availability check failed for target_agent=%s", target_agent, exc_info=True)
      return False

  async def _checkpoint_is_done(self, *, job: JobRecord, stage: str, section_index: int | None) -> bool:
    """Return True when the current stage/section checkpoint is already complete."""
    checkpoint = await self._jobs_repo.get_checkpoint(job_id=job.job_id, stage=stage, section_index=section_index)
    return bool(checkpoint and checkpoint.state == "done")

  async def _checkpoint_mark_state(self, *, job: JobRecord, stage: str, section_index: int | None, state: str, artifact_refs_json: dict[str, Any] | None = None, last_error: str | None = None) -> None:
    """Persist checkpoint state transitions for resumable execution."""
    current = await self._jobs_repo.get_checkpoint(job_id=job.job_id, stage=stage, section_index=section_index)
    attempt_count = int(current.attempt_count) + (1 if state == "error" else 0) if current else (1 if state == "error" else 0)
    await self._jobs_repo.upsert_checkpoint(job_id=job.job_id, stage=stage, section_index=section_index, state=state, artifact_refs_json=artifact_refs_json, attempt_count=attempt_count, last_error=last_error)

  async def _checkpoint_claim_state(self, *, job: JobRecord, stage: str, section_index: int | None) -> str:
    """Atomically claim one checkpoint and return claim status."""
    current = await self._jobs_repo.get_checkpoint(job_id=job.job_id, stage=stage, section_index=section_index)
    if current is not None and current.state == "done":
      return "done"
    if current is None:
      await self._jobs_repo.upsert_checkpoint(job_id=job.job_id, stage=stage, section_index=section_index, state="pending")
    claim_fn = getattr(self._jobs_repo, "claim_checkpoint", None)
    if callable(claim_fn):
      claimed = await claim_fn(job_id=job.job_id, stage=stage, section_index=section_index)
      if claimed is not None:
        return "claimed"
      refreshed = await self._jobs_repo.get_checkpoint(job_id=job.job_id, stage=stage, section_index=section_index)
      if refreshed is not None and refreshed.state == "done":
        return "done"
      return "locked"
    await self._checkpoint_mark_state(job=job, stage=stage, section_index=section_index, state="running")
    return "claimed"

  async def _fan_out_section_children(
    self, *, job: JobRecord, updated_parent: JobRecord, tracker: JobProgressTracker, lesson_id: str, section_number: int, db_section_id: int | None, section_payload: dict[str, Any], topic: str, learner_level: str | None
  ) -> None:
    """Queue downstream section agents for unfinished checkpoints only."""
    if db_section_id is None:
      return
    removed_widget_refs: list[str] = []
    if not await self._checkpoint_is_done(job=job, stage="illustration", section_index=section_number):
      try:
        await self._jobs_repo.upsert_checkpoint(job_id=job.job_id, stage="illustration", section_index=section_number, state="pending", artifact_refs_json={"section_id": db_section_id})
        await self._create_child_job(
          parent_job=updated_parent,
          target_agent="illustration",
          payload={"section_index": section_number, "section_id": db_section_id, "lesson_id": lesson_id, "topic": topic, "section_data": section_payload},
          lesson_id=lesson_id,
          section_id=db_section_id,
        )
      except QuotaExceededError:
        await self._jobs_repo.update_job(job.job_id, logs=tracker.logs + [f"Illustration job skipped for section {section_number}: quota unavailable."])
        removed_widget_refs.append(f"{section_number}.1.1.illustration")
        section_payload.pop("illustration", None)
    if not await self._checkpoint_is_done(job=job, stage="tutor", section_index=section_number):
      try:
        await self._jobs_repo.upsert_checkpoint(job_id=job.job_id, stage="tutor", section_index=section_number, state="pending", artifact_refs_json={"section_id": db_section_id})
        await self._create_child_job(
          parent_job=updated_parent,
          target_agent="tutor",
          payload={"section_index": section_number, "section_id": db_section_id, "topic": topic, "section_data": section_payload, "learning_data_points": section_payload.get("learning_data_points", [])},
          lesson_id=lesson_id,
          section_id=db_section_id,
        )
      except QuotaExceededError:
        await self._jobs_repo.update_job(job.job_id, logs=tracker.logs + [f"Tutor job skipped for section {section_number}: quota unavailable."])
        removed_widget_refs.append(f"{section_number}.1.1.tutor")
    if _section_contains_fenster(section_payload) and not await self._checkpoint_is_done(job=job, stage="fenster_builder", section_index=section_number):
      await self._jobs_repo.upsert_checkpoint(job_id=job.job_id, stage="fenster_builder", section_index=section_number, state="pending", artifact_refs_json={"section_id": db_section_id})
      fenster_widget_ids = _extract_widget_public_ids(section_payload, widget_type="fenster")
      for fenster_public_id in fenster_widget_ids:
        try:
          await self._create_child_job(
            parent_job=updated_parent,
            target_agent="fenster_builder",
            payload={
              "lesson_id": lesson_id,
              "section_id": db_section_id,
              "widget_public_ids": [fenster_public_id],
              "concept_context": f"Fenster widget for section {section_number} in topic {topic}",
              "target_audience": learner_level or "Student",
              "technical_constraints": {},
            },
            lesson_id=lesson_id,
            section_id=db_section_id,
          )
        except QuotaExceededError:
          await self._jobs_repo.update_job(job.job_id, logs=tracker.logs + [f"Fenster job skipped for section {section_number}: quota unavailable for widget {fenster_public_id}."])
          removed_widget_refs.extend(_remove_widget_items_by_public_id(section_payload=section_payload, section_index=section_number, widget_type="fenster", public_ids=[fenster_public_id]))
          await _update_subsection_widget_status(section_id=db_section_id, widget_types=("fenster",), status="skipped", public_ids=[fenster_public_id])
    if removed_widget_refs:
      session_factory = get_session_factory()
      if session_factory is not None:
        async with session_factory() as session:
          section_row = await session.get(Section, db_section_id)
          if section_row is not None:
            existing_csv = str(section_row.removed_widgets_csv or "").strip()
            added_csv = ",".join(removed_widget_refs)
            section_row.removed_widgets_csv = f"{existing_csv},{added_csv}".strip(",") if existing_csv else added_csv
            section_row.content = section_payload
            section_row.content_shorthand = build_section_shorthand_content(section_payload)
            session.add(section_row)
            await session.commit()

  async def _process_planner_job(self, job: JobRecord) -> JobRecord | None:
    """Execute planner-only work and fan out one section-builder job per section."""
    planner_claim = await self._checkpoint_claim_state(job=job, stage="planner", section_index=None)
    if planner_claim == "done":
      await self._jobs_repo.append_event(job_id=job.job_id, event_type="checkpoint", message="Planner checkpoint already complete. Skipping generation.", payload_json={"stage": "planner"})
      return await self._jobs_repo.update_job(job.job_id, status="done", completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    if planner_claim == "locked":
      await self._jobs_repo.append_event(job_id=job.job_id, event_type="checkpoint", message="Planner checkpoint is locked by another worker; skipping duplicate execution.", payload_json={"stage": "planner"})
      return await self._jobs_repo.get_job(job.job_id)
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="planner", initial_logs=["Planner job picked up."])
    await tracker.set_phase(phase="planning", subphase="planner_start")
    lesson_request_id: int | None = None
    try:
      original_request_payload = job.request.get("payload") if isinstance(job.request.get("payload"), dict) else job.request
      request_meta = original_request_payload.get("_meta") if isinstance(original_request_payload.get("_meta"), dict) else {}
      raw_lesson_request_id = request_meta.get("lesson_request_id")
      if raw_lesson_request_id is not None:
        lesson_request_id = int(raw_lesson_request_id)
      request_payload = _strip_internal_request_fields(job.request)
      request_model = GenerateLessonRequestStruct.model_validate(request_payload)
      section_count = {"highlights": 2, "detailed": 6, "training": 10}.get(str(request_model.depth).lower(), 2)
      generation_request = GenerationRequest(
        topic=request_model.topic,
        prompt=request_model.details,
        outcomes=request_model.outcomes,
        depth=request_model.depth,
        section_count=section_count,
        blueprint=request_model.blueprint,
        teaching_style=request_model.teaching_style,
        lesson_language=request_model.lesson_language,
        secondary_language=request_model.secondary_language,
        learner_level=request_model.learner_level,
        widgets=request_model.widgets,
      )
      # Resolve runtime config for per-tenant model overrides.
      runtime_config: dict[str, Any] = {}
      if job.user_id:
        session_factory = get_session_factory()
        if session_factory is not None:
          async with session_factory() as session:
            user = await get_user_by_id(session, job.user_id)
            if user is not None:
              tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
              runtime_config = await resolve_effective_runtime_config(session, settings=self._settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)

      provider, model_name = get_planner_model(runtime_config)
      model_instance = get_model_for_mode(provider, model_name, agent="planner")
      planner_agent = PlannerAgent(model=model_instance, prov=provider, schema=SchemaService())
      lesson_id = str(job.lesson_id or generate_lesson_id())
      job_metadata = {"settings": self._settings, "lesson_id": lesson_id}
      if job.user_id:
        job_metadata["user_id"] = str(job.user_id)
      job_ctx = JobContext(job_id=job.job_id, created_at=datetime.utcnow(), provider=provider, model=model_name or "default", request=generation_request, metadata=job_metadata)
      lesson_plan = await planner_agent.run(generation_request, job_ctx)
      repo = _get_repo(self._settings)
      existing_lesson = await repo.get_lesson(lesson_id)
      created_at = existing_lesson.created_at if existing_lesson else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
      lesson_record = LessonRecord(
        lesson_id=lesson_id,
        user_id=str(job.user_id) if job.user_id else None,
        topic=request_model.topic,
        title=request_model.topic,
        created_at=created_at,
        schema_version=request_model.schema_version or self._settings.schema_version,
        prompt_version=self._settings.prompt_version,
        provider_a=provider,
        model_a=model_name or "default",
        provider_b="pending",
        model_b="pending",
        status="generating",
        latency_ms=0,
        idempotency_key=request_model.idempotency_key,
        lesson_plan=lesson_plan.model_dump(mode="python"),
        lesson_request_id=lesson_request_id,
      )
      await repo.upsert_lesson(lesson_record)
      if lesson_request_id is not None:
        session_factory = get_session_factory()
        if session_factory is not None:
          async with session_factory() as session:
            lesson_request_row = await session.get(LessonRequest, int(lesson_request_id))
            if lesson_request_row is not None:
              lesson_request_row.status = "planned"
              session.add(lesson_request_row)
              await session.commit()
      done_payload = {
        "status": "done",
        "phase": "complete",
        "progress": 100.0,
        "logs": tracker.logs + ["Planner completed successfully."],
        "result_json": {"lesson_id": lesson_id, "planned_sections": len(lesson_plan.sections)},
        "lesson_id": lesson_id,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
      }
      updated_parent = await self._jobs_repo.update_job(job.job_id, **done_payload)
      if updated_parent is None:
        return None
      await self._checkpoint_mark_state(job=job, stage="planner", section_index=None, state="done", artifact_refs_json={"lesson_id": lesson_id, "planned_sections": len(lesson_plan.sections)})
      for plan_section in lesson_plan.sections:
        section_number = int(plan_section.section_number)
        await self._jobs_repo.upsert_checkpoint(job_id=job.job_id, stage="section_builder", section_index=section_number, state="pending", artifact_refs_json={"lesson_id": lesson_id})
        child_payload = {
          "lesson_id": lesson_id,
          "section_number": section_number,
          "plan_section": plan_section.model_dump(mode="python"),
          "generation_request": generation_request.model_dump(mode="python"),
          "schema_version": request_model.schema_version or self._settings.schema_version,
        }
        try:
          await self._create_child_job(parent_job=updated_parent, target_agent="section_builder", payload=child_payload, lesson_id=lesson_id, section_id=None)
        except QuotaExceededError as exc:
          await self._jobs_repo.update_job(job.job_id, logs=tracker.logs + [f"Planner stopped section fan-out due to quota: {exc}"])
          break
      return await self._jobs_repo.get_job(job.job_id)
    except Exception as exc:  # noqa: BLE001
      self._logger.error("Planner job failed", exc_info=True)
      await _update_lesson_request_status(lesson_request_id=lesson_request_id, status="failed")
      await self._checkpoint_mark_state(job=job, stage="planner", section_index=None, state="error", last_error=str(exc))
      await tracker.fail(phase="failed", message=f"Planner job failed: {exc}")
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs, error_json={"message": str(exc)})
      return None

  async def _process_section_builder_job(self, job: JobRecord) -> JobRecord | None:
    """Execute one section-builder unit and fan out section child jobs."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="section_builder", initial_logs=["Section builder job picked up."])
    await tracker.set_phase(phase="building", subphase="section_builder_start")
    lesson_id = ""
    section_number = 0
    db_section_id: int | None = None
    generation_topic = "unknown"
    learner_level: str | None = None
    try:
      wrapped_payload = job.request.get("payload")
      request_payload = wrapped_payload if isinstance(wrapped_payload, dict) else job.request
      lesson_id = str(job.lesson_id or request_payload.get("lesson_id") or "")
      if lesson_id == "":
        raise RuntimeError("Section builder job missing lesson_id.")
      section_number = int(request_payload.get("section_number") or 0)
      if section_number <= 0:
        raise RuntimeError("Section builder job missing section_number.")
      section_claim = await self._checkpoint_claim_state(job=job, stage="section_builder", section_index=section_number)
      if section_claim == "done":
        await self._jobs_repo.append_event(job_id=job.job_id, event_type="checkpoint", message=f"Section {section_number} checkpoint already complete. Skipping generation.", payload_json={"stage": "section_builder", "section_index": section_number})
        return await self._jobs_repo.update_job(job.job_id, status="done", completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
      if section_claim == "locked":
        await self._jobs_repo.append_event(
          job_id=job.job_id, event_type="checkpoint", message=f"Section {section_number} checkpoint is locked by another worker; skipping duplicate execution.", payload_json={"stage": "section_builder", "section_index": section_number}
        )
        return await self._jobs_repo.get_job(job.job_id)
      session_factory = get_session_factory()
      if session_factory is not None:
        async with session_factory() as session:
          existing_section = (await session.execute(select(Section).where(Section.lesson_id == lesson_id, Section.order_index == section_number).limit(1))).scalar_one_or_none()
          if existing_section is not None and existing_section.status == "completed" and isinstance(existing_section.content, dict) and existing_section.content:
            db_section_id = int(existing_section.section_id)
            done_payload = {
              "status": "done",
              "phase": "complete",
              "progress": 100.0,
              "logs": tracker.logs + [f"Section {section_number} already exists. Skipping regeneration."],
              "result_json": {"lesson_id": lesson_id, "section_number": section_number, "section_id": db_section_id, "skipped": True},
              "section_id": db_section_id,
              "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            await self._checkpoint_mark_state(job=job, stage="section_builder", section_index=section_number, state="done", artifact_refs_json={"section_id": db_section_id, "skipped": True})
            updated_parent = await self._jobs_repo.update_job(job.job_id, **done_payload)
            generation_payload = request_payload.get("generation_request") or {}
            generation_topic = str(generation_payload.get("topic") or "unknown")
            learner_level = str(generation_payload.get("learner_level") or "").strip() or None
            if updated_parent is not None:
              await self._fan_out_section_children(
                job=job, updated_parent=updated_parent, tracker=tracker, lesson_id=lesson_id, section_number=section_number, db_section_id=db_section_id, section_payload=dict(existing_section.content), topic=generation_topic, learner_level=learner_level
              )
            return updated_parent
      generation_payload = request_payload.get("generation_request") or {}
      generation_request = GenerationRequest.model_validate(generation_payload)
      generation_topic = str(generation_request.topic or "unknown")
      learner_level = str(generation_request.learner_level or "").strip() or None
      plan_section = PlanSection.model_validate(request_payload.get("plan_section") or {})
      # Resolve runtime config for per-tenant model overrides.
      runtime_config: dict[str, Any] = {}
      if job.user_id:
        session_factory = get_session_factory()
        if session_factory is not None:
          async with session_factory() as session:
            user = await get_user_by_id(session, job.user_id)
            if user is not None:
              tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
              runtime_config = await resolve_effective_runtime_config(session, settings=self._settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)

      provider, model_name = get_section_builder_model(runtime_config)
      model_instance = get_model_for_mode(provider, model_name, agent="section_builder")
      section_agent = SectionBuilder(model=model_instance, prov=provider, schema=SchemaService())
      metadata = {"settings": self._settings, "lesson_id": lesson_id, "schema_version": str(request_payload.get("schema_version") or self._settings.schema_version), "structured_output": True}
      if job.user_id:
        metadata["user_id"] = str(job.user_id)
      job_ctx = JobContext(job_id=job.job_id, created_at=datetime.utcnow(), provider=provider, model=model_name or "default", request=generation_request, metadata=metadata)
      structured = await section_agent.run(plan_section, job_ctx)
      non_blocking_validation_errors = _extract_non_blocking_length_errors(structured.validation_errors)
      if non_blocking_validation_errors:
        await self._jobs_repo.update_job(job.job_id, logs=tracker.logs + [f"Section {section_number} ignored non-blocking length violations and continued generation."])
        structured.validation_errors = [err for err in structured.validation_errors if err not in non_blocking_validation_errors]
      if structured.validation_errors:
        repair_provider, repair_model_name = get_repair_model(runtime_config)
        repair_model_instance = get_model_for_mode(repair_provider, repair_model_name, agent="repairer")
        repair_agent = RepairerAgent(model=repair_model_instance, prov=repair_provider, schema=SchemaService())
        repair_input = RepairInput(section=SectionDraft(section_number=section_number, title=plan_section.title, plan_section=plan_section, raw_text=""), structured=structured)
        repair_result = await repair_agent.run(repair_input, job_ctx)
        if repair_result.errors:
          db_section_id = int(structured.db_section_id) if structured.db_section_id is not None else None
          await _update_section_status(section_id=db_section_id, status="failed")
          await _mark_lesson_pipeline_failed(lesson_id=lesson_id)
          await self._checkpoint_mark_state(job=job, stage="section_builder", section_index=section_number, state="error", last_error="; ".join([str(item) for item in repair_result.errors]))
          await tracker.fail(phase="failed", message=f"Section {section_number} failed validation and single repair attempt.")
          await self._jobs_repo.update_job(
            job.job_id,
            status="error",
            phase="failed",
            progress=100.0,
            logs=tracker.logs,
            result_json={"lesson_id": lesson_id, "section_number": section_number, "errors": repair_result.errors},
            error_json={"message": "SECTION_VALIDATION_REPAIR_FAILED", "errors": [str(item) for item in repair_result.errors]},
          )
          return None
        structured.payload = repair_result.fixed_json
        structured.validation_errors = []
      db_section_id = int(structured.db_section_id) if structured.db_section_id is not None else None
      done_payload = {
        "status": "done",
        "phase": "complete",
        "progress": 100.0,
        "logs": tracker.logs + [f"Section {section_number} completed successfully."],
        "result_json": {"lesson_id": lesson_id, "section_number": section_number, "section_id": db_section_id},
        "section_id": db_section_id,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
      }
      updated_parent = await self._jobs_repo.update_job(job.job_id, **done_payload)
      if updated_parent is None:
        return None
      await self._checkpoint_mark_state(job=job, stage="section_builder", section_index=section_number, state="done", artifact_refs_json={"section_id": db_section_id})
      await self._fan_out_section_children(
        job=job, updated_parent=updated_parent, tracker=tracker, lesson_id=lesson_id, section_number=section_number, db_section_id=db_section_id, section_payload=structured.payload, topic=generation_topic, learner_level=learner_level
      )
      return await self._jobs_repo.get_job(job.job_id)
    except Exception as exc:  # noqa: BLE001
      self._logger.error("Section builder job failed", exc_info=True)
      await _update_section_status(section_id=db_section_id, status="failed")
      if lesson_id:
        await _mark_lesson_pipeline_failed(lesson_id=lesson_id)
      if section_number > 0:
        await self._checkpoint_mark_state(job=job, stage="section_builder", section_index=section_number, state="error", last_error=str(exc))
      await tracker.fail(phase="failed", message=f"Section builder job failed: {exc}")
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs, error_json={"message": str(exc)})
      return None

  async def _process_maintenance_job(self, job: JobRecord) -> JobRecord | None:
    """Execute a background maintenance job (retention, cleanup, etc.)."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="maintenance", initial_logs=["Maintenance job acknowledged."])
    await tracker.set_phase(phase="maintenance", subphase="start")
    wrapped_payload = job.request.get("payload")
    request_payload = wrapped_payload if isinstance(wrapped_payload, dict) else job.request
    action = request_payload.get("action")
    if not isinstance(action, str) or action.strip() == "":
      await tracker.fail(phase="failed", message="Maintenance job missing action.")
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs)
      return None
    action = action.strip().lower()
    session_factory = get_session_factory()
    if session_factory is None:
      await tracker.fail(phase="failed", message="Database is not initialized.")
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs)
      return None
    try:
      if action == "archive_old_lessons":
        async with session_factory() as session:
          archived_count = await archive_old_lessons(session, settings=self._settings)
        tracker.add_logs(f"Archived {archived_count} lesson(s).")
        result_json: dict[str, Any] = {"action": action, "archived_count": archived_count}
      elif action in {"data_export", "data_hydrate"}:
        raw_run_id = request_payload.get("run_id")
        if not isinstance(raw_run_id, str) or raw_run_id.strip() == "":
          raise RuntimeError("Data transfer maintenance action requires run_id.")
        try:
          run_uuid = uuid.UUID(raw_run_id)
        except ValueError as exc:
          raise RuntimeError("Data transfer maintenance action received invalid run_id.") from exc

        async with session_factory() as session:
          run = (await session.execute(select(DataTransferRun).where(DataTransferRun.id == run_uuid))).scalar_one_or_none()
          if run is None:
            raise RuntimeError(f"Data transfer run not found: {raw_run_id}")
          if str(run.job_id) != str(job.job_id):
            raise RuntimeError("Data transfer run/job mismatch.")
          if action == "data_export":
            export_result = await execute_export_run(session=session, settings=self._settings, run=run)
            run.status = "done"
            run.completed_at = datetime.now(UTC)
            run.error_message = None
            run.artifacts_json = export_result["artifacts_json"]
            run.result_json = {"artifact_count": export_result["artifact_count"], "run_type": "export"}
            session.add(run)
            await session.commit()
            tracker.add_logs(f"Export artifacts generated: {export_result['artifact_count']}.")
            result_json = {"action": action, "run_id": str(run.id), "artifact_count": export_result["artifact_count"]}
          else:
            hydrate_result = await execute_hydrate_run(session=session, settings=self._settings, run=run)
            run.status = "done"
            run.completed_at = datetime.now(UTC)
            run.error_message = None
            run.result_json = hydrate_result
            session.add(run)
            await session.commit()
            tracker.add_logs("Hydrate completed successfully.")
            result_json = {"action": action, "run_id": str(run.id), **hydrate_result}
      else:
        await tracker.fail(phase="failed", message="Unsupported maintenance action.")
        await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs)
        return None
      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
      payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs, "result_json": result_json, "completed_at": completed_at}
      updated = await self._jobs_repo.update_job(job.job_id, **payload)
      return updated
    except Exception as exc:  # noqa: BLE001
      self._logger.error("Maintenance job failed", exc_info=True)
      if action in {"data_export", "data_hydrate"}:
        raw_run_id = request_payload.get("run_id")
        if isinstance(raw_run_id, str):
          try:
            run_uuid = uuid.UUID(raw_run_id)
          except ValueError:
            run_uuid = None
          if run_uuid is not None:
            async with session_factory() as session:
              run = (await session.execute(select(DataTransferRun).where(DataTransferRun.id == run_uuid))).scalar_one_or_none()
              if run is not None:
                run.status = "error"
                run.completed_at = datetime.now(UTC)
                run.error_message = str(exc)
                session.add(run)
                await session.commit()
      await tracker.fail(phase="failed", message=f"Maintenance job failed: {exc}")
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs, error_json={"message": str(exc)})
      return None

  async def _process_fenster_build(self, job: JobRecord) -> JobRecord | None:
    """Execute Fenster Widget generation."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="fenster", initial_logs=["Fenster job picked up."])
    await tracker.set_phase(phase="building", subphase="generating_code")
    section_id = 0
    section_index = 0
    widget_public_ids: list[str] = []

    try:
      wrapped_payload = job.request.get("payload")
      payload = wrapped_payload if isinstance(wrapped_payload, dict) else job.request
      section_index = int(payload.get("section_index") or 0)
      fenster_checkpoint_index = section_index if section_index > 0 else None
      fenster_claim = await self._checkpoint_claim_state(job=job, stage="fenster_builder", section_index=fenster_checkpoint_index)
      if fenster_claim == "done":
        await self._jobs_repo.append_event(job_id=job.job_id, event_type="checkpoint", message="Fenster checkpoint already complete. Skipping generation.", payload_json={"stage": "fenster_builder", "section_index": section_index})
        return await self._jobs_repo.update_job(job.job_id, status="done", completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
      if fenster_claim == "locked":
        await self._jobs_repo.append_event(job_id=job.job_id, event_type="checkpoint", message="Fenster checkpoint is locked by another worker; skipping duplicate execution.", payload_json={"stage": "fenster_builder", "section_index": section_index})
        return await self._jobs_repo.get_job(job.job_id)
      # Resolve runtime config for per-tenant model overrides.
      runtime_config: dict[str, Any] = {}
      if job.user_id:
        session_factory = get_session_factory()
        if session_factory is not None:
          async with session_factory() as session:
            user = await get_user_by_id(session, job.user_id)
            if user is not None:
              tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
              runtime_config = await resolve_effective_runtime_config(session, settings=self._settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)

      provider, model_name = get_fenster_model(runtime_config)
      model_instance = get_model_for_mode(provider, model_name, agent="fenster_builder")

      schema_service = SchemaService()

      usage_list = []

      def usage_sink(u: dict[str, Any]) -> None:
        usage_list.append(u)

      agent = FensterBuilderAgent(model=model_instance, prov=provider, schema=schema_service, use=usage_sink)

      section_id = int(job.section_id or payload.get("section_id") or 0)
      widget_public_ids = [str(item) for item in list(payload.get("widget_public_ids") or []) if str(item).strip()]
      # Use a dummy request for context
      dummy_req = GenerationRequest(topic="widget_build", depth="highlights", section_count=2)
      # Forward settings and user metadata for agent-scoped quota reservations.
      job_metadata = {"settings": self._settings}
      if job.user_id:
        job_metadata["user_id"] = str(job.user_id)
      job_ctx = JobContext(job_id=job.job_id, created_at=datetime.utcnow(), provider=provider, model=model_name, request=dummy_req, metadata=job_metadata)

      html_content = await agent.run(payload, job_ctx)

      # Compress
      compressed = compress_html(html_content)

      # Insert DB
      fenster_resource_id = ""
      pricing_table: dict[str, dict[str, tuple[float, float]]] = {}
      session_factory = get_session_factory()
      if session_factory:
        async with session_factory() as session:
          existing_widget = await _resolve_fenster_widget_by_subsection_mapping(session=session, section_id=section_id, subsection_widget_public_ids=widget_public_ids)
          fenster_resource_id = existing_widget.public_id if existing_widget is not None else ""
          if fenster_resource_id == "":
            fenster_resource_id = generate_nanoid()
          if existing_widget is None:
            existing_widget = (await session.execute(select(FensterWidget).where(FensterWidget.public_id == fenster_resource_id).limit(1))).scalar_one_or_none()
          if existing_widget is None:
            existing_widget = FensterWidget(fenster_id=uuid.uuid4(), public_id=fenster_resource_id, creator_id=str(job.user_id or ""), status="completed", is_archived=False, type=FensterWidgetType.INLINE_BLOB, content=compressed, url=None)
            session.add(existing_widget)
          else:
            existing_widget.creator_id = str(job.user_id or existing_widget.creator_id)
            existing_widget.status = "completed"
            existing_widget.is_archived = False
            existing_widget.type = FensterWidgetType.INLINE_BLOB
            existing_widget.content = compressed
            existing_widget.url = None
            session.add(existing_widget)
          pricing_table = await load_pricing_table(session)
          await session.commit()

      if section_id > 0:
        await _update_subsection_widget_status(section_id=section_id, widget_types=("fenster",), status="completed", widget_id=fenster_resource_id, public_ids=widget_public_ids)

      # Calculate cost using database-backed pricing.
      total_cost = calculate_total_cost(usage_list, pricing_table, provider=provider)
      cost_summary = _summarize_cost(usage_list, total_cost)
      await tracker.set_cost(cost_summary)

      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

      result_json = {"fenster_resource_id": fenster_resource_id}

      payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs + ["Widget built and stored."], "result_json": result_json, "cost": cost_summary, "completed_at": completed_at}
      updated = await self._jobs_repo.update_job(job.job_id, **payload)
      await self._checkpoint_mark_state(job=job, stage="fenster_builder", section_index=section_index if section_index > 0 else None, state="done", artifact_refs_json={"section_id": section_id, "fenster_resource_id": fenster_resource_id})
      return updated

    except Exception as exc:
      # Gracefully handle quota disabled or exceeded by marking success-but-skipped or just done.
      # Since we don't have a partial-success status, "done" with logs is better than "error" for quota toggles.
      if "quota disabled" in str(exc) or isinstance(exc, QuotaExceededError):
        self._logger.info("Fenster quota disabled, skipping job %s", job.job_id)
        if section_id > 0:
          await _update_subsection_widget_status(section_id=section_id, widget_types=("fenster",), status="skipped", public_ids=widget_public_ids)
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs + ["Quota disabled. Skipping widget build."], "result_json": {}, "completed_at": completed_at}
        updated = await self._jobs_repo.update_job(job.job_id, **payload)
        await self._checkpoint_mark_state(job=job, stage="fenster_builder", section_index=section_index if section_index > 0 else None, state="done", artifact_refs_json={"section_id": section_id, "skipped": True})
        return updated

      self._logger.error("Fenster build failed", exc_info=True)
      if section_id > 0:
        await _update_subsection_widget_status(section_id=section_id, widget_types=("fenster",), status="failed", public_ids=widget_public_ids)
      await tracker.fail(phase="failed", message=f"Fenster build failed: {exc}")
      payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs, "error_json": {"message": str(exc)}}
      await self._jobs_repo.update_job(job.job_id, **payload)
      await self._checkpoint_mark_state(job=job, stage="fenster_builder", section_index=section_index if section_index > 0 else None, state="error", last_error=str(exc))
      return None

  async def _process_tutor_job(self, job: JobRecord) -> JobRecord | None:
    """Execute tutor generation."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="tutor", initial_logs=["Tutor job picked up."])
    await tracker.set_phase(phase="building", subphase="generating_audio")
    section_index = 0

    try:
      wrapped_payload = job.request.get("payload")
      payload = wrapped_payload if isinstance(wrapped_payload, dict) else job.request
      section_index = int(payload.get("section_index") or 0)
      tutor_checkpoint_index = section_index if section_index > 0 else None
      tutor_claim = await self._checkpoint_claim_state(job=job, stage="tutor", section_index=tutor_checkpoint_index)
      if tutor_claim == "done":
        await self._jobs_repo.append_event(job_id=job.job_id, event_type="checkpoint", message="Tutor checkpoint already complete. Skipping generation.", payload_json={"stage": "tutor", "section_index": section_index})
        return await self._jobs_repo.update_job(job.job_id, status="done", completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
      if tutor_claim == "locked":
        await self._jobs_repo.append_event(job_id=job.job_id, event_type="checkpoint", message="Tutor checkpoint is locked by another worker; skipping duplicate execution.", payload_json={"stage": "tutor", "section_index": section_index})
        return await self._jobs_repo.get_job(job.job_id)
      # Resolve runtime-configured provider/model and feature-gate status for tutor generation.
      session_factory = get_session_factory()
      runtime_config: dict[str, Any] = {}
      tutor_mode_enabled = False
      pricing_table: dict[str, dict[str, tuple[float, float]]] = {}
      if session_factory:
        parsed_user_id = None
        if job.user_id:
          try:
            parsed_user_id = uuid.UUID(str(job.user_id))
          except ValueError:
            parsed_user_id = None

        async with session_factory() as session:
          if parsed_user_id is not None:
            user = await get_user_by_id(session, parsed_user_id)
            if user is not None:
              tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
              runtime_config = await resolve_effective_runtime_config(session, settings=self._settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
              decision = await resolve_feature_flag_decision(session, key="feature.tutor.mode", org_id=user.org_id, subscription_tier_id=tier_id, user_id=user.id)
              tutor_mode_enabled = bool(decision.enabled)

          pricing_table = await load_pricing_table(session)

      if not tutor_mode_enabled:
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs + ["Tutor mode disabled. Skipping tutor generation."], "result_json": {"tutor_ids": [], "count": 0, "skipped": True}, "completed_at": completed_at}
        updated = await self._jobs_repo.update_job(job.job_id, **payload)
        await self._checkpoint_mark_state(job=job, stage="tutor", section_index=section_index if section_index > 0 else None, state="done", artifact_refs_json={"section_index": section_index, "skipped": True})
        return updated

      provider, model_name = get_tutor_model(runtime_config)

      model_instance = get_model_for_mode(provider, model_name or None, agent="tutor")
      schema_service = SchemaService()

      usage_list = []

      def usage_sink(u: dict[str, Any]) -> None:
        usage_list.append(u)

      agent = TutorAgent(model=model_instance, prov=provider, schema=schema_service, use=usage_sink)

      # Context
      dummy_req = GenerationRequest(topic=payload.get("topic", "unknown"), depth="highlights", section_count=1)
      # Forward settings and user metadata for agent-scoped quota reservations.
      job_metadata = {"settings": self._settings}
      if job.user_id:
        job_metadata["user_id"] = str(job.user_id)
      job_ctx = JobContext(job_id=job.job_id, created_at=datetime.utcnow(), provider=provider, model=model_name or "default", request=dummy_req, metadata=job_metadata)

      audio_ids = await agent.run(payload, job_ctx)
      section_id = int(payload.get("section_id") or 0)
      if section_id > 0 and audio_ids:
        session_factory = get_session_factory()
        if session_factory is not None:
          async with session_factory() as session:
            section_row = await session.get(Section, section_id)
            if section_row is not None:
              section_row.tutor_id = int(audio_ids[0])
              session.add(section_row)
              await session.commit()

      # Cost
      total_cost = calculate_total_cost(usage_list, pricing_table, provider=provider)
      cost_summary = _summarize_cost(usage_list, total_cost)
      await tracker.set_cost(cost_summary)

      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
      result_json = {"tutor_ids": audio_ids, "count": len(audio_ids)}

      payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs + [f"Generated {len(audio_ids)} audio segments."], "result_json": result_json, "cost": cost_summary, "completed_at": completed_at}
      updated = await self._jobs_repo.update_job(job.job_id, **payload)
      await self._checkpoint_mark_state(job=job, stage="tutor", section_index=section_index if section_index > 0 else None, state="done", artifact_refs_json={"section_index": section_index, "count": len(audio_ids)})
      return updated

    except Exception as exc:
      self._logger.error("Tutor job failed", exc_info=True)
      await tracker.fail(phase="failed", message=f"Tutor job failed: {exc}")
      payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs, "error_json": {"message": str(exc)}}
      await self._jobs_repo.update_job(job.job_id, **payload)
      await self._checkpoint_mark_state(job=job, stage="tutor", section_index=section_index if section_index > 0 else None, state="error", last_error=str(exc))
      return None

  async def _process_illustration_job(self, job: JobRecord) -> JobRecord | None:
    """Execute section illustration generation and persistence."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="illustration", initial_logs=["Illustration job picked up."])
    await tracker.set_phase(phase="building", subphase="generating_image")

    wrapped_payload = job.request.get("payload")
    payload = wrapped_payload if isinstance(wrapped_payload, dict) else job.request
    section_id = int(payload.get("section_id") or 0)
    section_index = int(payload.get("section_index") or 0)
    illustration_row_id: int | None = None
    uploaded_object_name: str | None = None
    generation_caption: str | None = None
    generation_prompt: str | None = None
    generation_keywords: list[str] | None = None
    finalized_success = False

    try:
      illustration_checkpoint_index = section_index if section_index > 0 else None
      illustration_claim = await self._checkpoint_claim_state(job=job, stage="illustration", section_index=illustration_checkpoint_index)
      if illustration_claim == "done":
        await self._jobs_repo.append_event(job_id=job.job_id, event_type="checkpoint", message=f"Illustration checkpoint already complete for section_index={section_index}.", payload_json={"stage": "illustration", "section_index": section_index})
        return await self._jobs_repo.update_job(job.job_id, status="done", completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
      if illustration_claim == "locked":
        await self._jobs_repo.append_event(
          job_id=job.job_id, event_type="checkpoint", message=f"Illustration checkpoint is locked by another worker for section_index={section_index}; skipping duplicate execution.", payload_json={"stage": "illustration", "section_index": section_index}
        )
        return await self._jobs_repo.get_job(job.job_id)
      if section_id <= 0:
        raise ValueError("Illustration job payload missing valid section_id.")

      session_factory = get_session_factory()
      if session_factory is None:
        raise RuntimeError("Database session factory unavailable.")

      # Resolve runtime config for pricing and model overrides.
      runtime_config: dict[str, Any] = {}
      pricing_table: dict[str, dict[str, tuple[float, float]]] = {}
      parsed_user_id = None
      if job.user_id:
        try:
          parsed_user_id = uuid.UUID(str(job.user_id))
        except ValueError:
          parsed_user_id = None

      async with session_factory() as session:
        if parsed_user_id is not None:
          user = await get_user_by_id(session, parsed_user_id)
          if user is not None:
            tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
            runtime_config = await resolve_effective_runtime_config(session, settings=self._settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)

        pricing_table = await load_pricing_table(session)

      storage_client = build_storage_client(self._settings)

      # Resolve section row first to support idempotency checks and fallback metadata.
      async with session_factory() as session:
        section_stmt = select(Section).where(Section.section_id == section_id)
        section_result = await session.execute(section_stmt)
        section_row = section_result.scalar_one_or_none()
        if section_row is None:
          raise RuntimeError(f"Section {section_id} not found for illustration job.")
        section_content = dict(section_row.content or {})

      fallback_caption, fallback_prompt, fallback_keywords = _derive_illustration_metadata_from_payload(payload, section_content)
      generation_caption = fallback_caption
      generation_prompt = fallback_prompt
      generation_keywords = fallback_keywords

      # Check active section pointer first so retried child jobs are idempotent.
      async with session_factory() as session:
        section_row = await session.get(Section, section_id)
        if section_row is None:
          raise RuntimeError(f"Section {section_id} not found for illustration job.")
        existing_illustration_id = int(section_row.illustration_id) if section_row.illustration_id is not None else _extract_section_illustration_id(section_row.content)
        if existing_illustration_id is not None:
          existing_illustration = await session.get(Illustration, existing_illustration_id)
          if existing_illustration is not None and existing_illustration.status == "completed" and await storage_client.exists(existing_illustration.storage_object_name):
            total_cost = calculate_total_cost([], pricing_table)
            cost_summary = _summarize_cost([], total_cost)
            await tracker.set_cost(cost_summary)
            completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            result_json = {"section_id": section_id, "illustration_id": int(existing_illustration.id), "resource_id": str(existing_illustration.public_id), "image_name": existing_illustration.storage_object_name, "skipped": True}
            async with session_factory() as session:
              section_row = await session.get(Section, section_id)
              if section_row is not None:
                section_row.illustration_id = int(existing_illustration.id)
                session.add(section_row)
                await session.commit()
            update_payload = {
              "status": "done",
              "phase": "complete",
              "progress": 100.0,
              "logs": tracker.logs + [f"Illustration already exists for section {section_id}. Skipping regeneration."],
              "result_json": result_json,
              "cost": cost_summary,
              "completed_at": completed_at,
            }
            updated = await self._jobs_repo.update_job(job.job_id, **update_payload)
            await _update_subsection_widget_status(section_id=section_id, widget_types=("illustration",), status="completed", widget_id=str(existing_illustration.id))
            await self._checkpoint_mark_state(
              job=job, stage="illustration", section_index=section_index if section_index > 0 else None, state="done", artifact_refs_json={"section_id": section_id, "illustration_id": int(existing_illustration.id), "skipped": True}
            )
            return updated

      # Resolve runtime-configured provider/model for the illustration agent.
      provider, model_name = get_illustration_model(runtime_config)
      model_instance = get_model_for_mode(provider, model_name or None, agent="illustration")
      schema_service = SchemaService()
      usage_list: list[dict[str, Any]] = []

      def usage_sink(usage_entry: dict[str, Any]) -> None:
        usage_list.append(usage_entry)

      agent = IllustrationAgent(model=model_instance, prov=provider, schema=schema_service, use=usage_sink)
      topic = str(payload.get("topic") or "unknown")
      dummy_req = GenerationRequest(topic=topic, depth="highlights", section_count=1)
      job_metadata = {"settings": self._settings}
      if job.user_id:
        job_metadata["user_id"] = str(job.user_id)
      job_ctx = JobContext(job_id=job.job_id, created_at=datetime.utcnow(), provider=provider, model=model_name or "default", request=dummy_req, metadata=job_metadata)
      generation = await agent.run(payload, job_ctx)
      generation_caption = str(generation["caption"])
      generation_prompt = str(generation["ai_prompt"])
      generation_keywords = [str(item) for item in list(generation["keywords"])]

      # Persist an explicit processing row before upload so failures always have a DB status trail.
      async with session_factory() as session:
        pending_object_name = f"tmp-{uuid.uuid4().hex}.webp"
        illustration_row = Illustration(
          public_id=generate_nanoid(),
          creator_id=str(job.user_id or ""),
          storage_bucket=storage_client.bucket_name,
          storage_object_name=pending_object_name,
          mime_type="image/webp",
          caption=generation_caption,
          ai_prompt=generation_prompt,
          keywords=generation_keywords,
          status="processing",
          is_archived=False,
          regenerate=False,
        )
        session.add(illustration_row)
        await session.commit()
        await session.refresh(illustration_row)
        illustration_row_id = int(illustration_row.id)

      object_name = f"{illustration_row.public_id}.webp"
      await storage_client.upload_webp(generation["image_bytes"], object_name, cache_control="public, max-age=3600")
      uploaded_object_name = object_name

      async with session_factory() as session:
        section_row = await session.get(Section, section_id)
        if section_row is None:
          raise RuntimeError(f"Section {section_id} not found for final illustration update.")
        illustration_row = await session.get(Illustration, illustration_row_id)
        if illustration_row is None:
          raise RuntimeError(f"Illustration row {illustration_row_id} not found for finalization.")
        illustration_row.storage_object_name = object_name
        illustration_row.status = "completed"
        illustration_row.caption = generation_caption
        illustration_row.ai_prompt = generation_prompt
        illustration_row.keywords = generation_keywords
        session.add(illustration_row)
        # Keep section payload as source of truth for the active illustration pointer.
        section_content = dict(section_row.content or {})
        existing_illustration = section_content.get("illustration")
        tracking_id: str | None = None
        if isinstance(existing_illustration, dict):
          raw_tracking_id = existing_illustration.get("id")
          if isinstance(raw_tracking_id, str) and raw_tracking_id.strip():
            tracking_id = raw_tracking_id.strip()
        if tracking_id is None:
          tracking_id = await _resolve_section_widget_public_id(section_id=section_id, widget_type="illustration")
        section_content["illustration"] = {"caption": generation_caption, "ai_prompt": generation_prompt, "keywords": generation_keywords, "resource_id": illustration_row.public_id, "id": tracking_id}
        shorthand_content = build_section_shorthand_content(section_content)
        section_row.content = section_content
        section_row.content_shorthand = shorthand_content
        section_row.illustration_id = illustration_row_id
        session.add(section_row)
        await session.commit()
      finalized_success = True
      await _update_subsection_widget_status(section_id=section_id, widget_types=("illustration",), status="completed", widget_id=str(illustration_row.public_id))

      total_cost = calculate_total_cost(usage_list, pricing_table, provider=provider)
      cost_summary = _summarize_cost(usage_list, total_cost)
      await tracker.set_cost(cost_summary)
      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
      result_json = {"section_id": section_id, "illustration_id": illustration_row_id, "resource_id": str(illustration_row.public_id), "image_name": uploaded_object_name or "", "mime_type": "image/webp"}
      update_payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs + [f"Illustration generated for section {section_id}."], "result_json": result_json, "cost": cost_summary, "completed_at": completed_at}
      updated = await self._jobs_repo.update_job(job.job_id, **update_payload)
      await self._checkpoint_mark_state(
        job=job, stage="illustration", section_index=section_index if section_index > 0 else None, state="done", artifact_refs_json={"section_id": section_id, "illustration_id": illustration_row_id, "image_name": uploaded_object_name}
      )
      return updated

    except Exception as exc:
      # Best-effort cleanup and state persistence so failures remain diagnosable.
      session_factory = get_session_factory()
      if session_factory is not None and not finalized_success:
        try:
          async with session_factory() as session:
            if illustration_row_id is None:
              failed_row = Illustration(
                public_id=generate_nanoid(),
                creator_id=str(job.user_id or ""),
                storage_bucket=self._settings.illustration_bucket,
                storage_object_name=uploaded_object_name or f"failed-{uuid.uuid4().hex}.webp",
                mime_type="image/webp",
                caption=generation_caption or "Illustration failed",
                ai_prompt=generation_prompt or "Illustration generation failed before prompt completion.",
                keywords=generation_keywords or ["failed", "illustration", "section", "error"],
                status="failed",
                is_archived=False,
                regenerate=False,
              )
              session.add(failed_row)
              await session.commit()
            else:
              illustration_row = await session.get(Illustration, illustration_row_id)
              if illustration_row is not None:
                illustration_row.status = "failed"
                if generation_caption:
                  illustration_row.caption = generation_caption
                if generation_prompt:
                  illustration_row.ai_prompt = generation_prompt
                if generation_keywords:
                  illustration_row.keywords = generation_keywords
                if uploaded_object_name:
                  illustration_row.storage_object_name = uploaded_object_name
                session.add(illustration_row)
                await session.commit()
        except Exception:  # noqa: BLE001
          self._logger.error("Illustration failure persistence hook failed.", exc_info=True)
      if uploaded_object_name and not finalized_success:
        try:
          storage_client = build_storage_client(self._settings)
          await storage_client.delete(uploaded_object_name)
        except Exception:  # noqa: BLE001
          self._logger.warning("Failed to remove partially uploaded illustration object %s", uploaded_object_name)
      self._logger.error("Illustration job failed", exc_info=True)
      if section_id > 0:
        await _update_subsection_widget_status(section_id=section_id, widget_types=("illustration",), status="failed")
      await tracker.fail(phase="failed", message=f"Illustration job failed: {exc}")
      payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs, "error_json": {"message": str(exc)}}
      await self._jobs_repo.update_job(job.job_id, **payload)
      await self._checkpoint_mark_state(job=job, stage="illustration", section_index=section_index if section_index > 0 else None, state="error", last_error=str(exc))
      return None

  async def process_queue(self, limit: int = 5) -> list[JobRecord]:
    """Process a small batch of queued jobs."""
    queued = await self._jobs_repo.find_queued(limit=limit)
    results: list[JobRecord] = []
    for job in queued:
      processed = await self.process_job(job)
      if processed:
        results.append(processed)
    return results


def _strip_internal_request_fields(request: dict[str, Any]) -> dict[str, Any]:
  """Drop internal-only metadata keys from stored job payloads before validation."""
  wrapped_payload = request.get("payload")
  request_payload = wrapped_payload if isinstance(wrapped_payload, dict) else request

  # Stored job requests may include internal metadata (e.g. _meta) that must not violate strict request models.
  cleaned = {key: value for key, value in request_payload.items() if not key.startswith("_")}

  # Drop deprecated model override fields so legacy jobs can still validate.
  cleaned.pop("models", None)
  cleaned.pop("checker_model", None)

  return cleaned


def _extract_quota_metric(error_message: str) -> str | None:
  """Extract a known quota metric name from an error message."""
  lowered = error_message.lower()
  known_metrics = ("lesson.generate", "section.generate", "tutor.generate", "fenster.widget.generate", "writing.check", "ocr.extract", "image.generate")
  for metric in known_metrics:
    # Match explicit metric names so job logs can report the exact exhausted resource.
    if metric in lowered:
      return metric
  if "quota" in lowered:
    return "unknown"
  return None


def _extract_non_blocking_length_errors(errors: list[str]) -> list[str]:
  """Return validation errors that only describe string/item length constraints."""
  non_blocking_errors: list[str] = []
  for error_message in errors:
    lowered = str(error_message).lower()
    if "length" not in lowered:
      continue
    if "expected `str`" in lowered or "expected `array`" in lowered:
      non_blocking_errors.append(error_message)
  return non_blocking_errors


def _extract_user_id(job_request: dict[str, Any]) -> uuid.UUID | None:
  """Extract the job creator user id from persisted job metadata."""
  raw_meta = job_request.get("_meta")
  if not isinstance(raw_meta, dict):
    return None

  raw_user_id = raw_meta.get("user_id")
  if not raw_user_id:
    return None

  try:
    return uuid.UUID(str(raw_user_id))
  except ValueError:
    return None


async def _notify_job_lesson_generated(*, settings: Settings, job_request: dict[str, Any], lesson_id: str, topic: str) -> None:
  """Best-effort notification when a lesson generation job completes."""
  user_id = _extract_user_id(job_request)
  if user_id is None:
    return

  session_factory = get_session_factory()
  if session_factory is None:
    return

  try:
    async with session_factory() as session:
      user = await get_user_by_id(session, user_id)
      if user is None:
        return

      await build_notification_service(settings).notify_lesson_generated(user_id=user.id, user_email=user.email, lesson_id=lesson_id, topic=topic)
  except Exception as exc:  # noqa: BLE001
    logging.getLogger(__name__).error("Failed sending job completion notification: %s", exc, exc_info=True)


async def _notify_job_failed(*, settings: Settings, job: JobRecord) -> None:
  """Best-effort in-app notification when a lesson job fails."""
  # Skip notifications when the job has no user association.
  if not job.user_id:
    return

  # Normalize the user id for downstream notification writes.
  try:
    user_id = uuid.UUID(str(job.user_id))
  except ValueError:
    return

  # Use the in-app notification channel for retries.
  service = build_notification_service(settings)
  try:
    await service.notify_in_app(user_id=user_id, template_id="lesson_job_failed_retry_v1", data={"job_id": job.job_id, "retry_target": job.job_id})
  except Exception as exc:  # noqa: BLE001
    logging.getLogger(__name__).error("Failed sending job failure notification: %s", exc, exc_info=True)


async def _notify_child_job_failed(*, settings: Settings, parent_job: JobRecord | None, child_job_id: str) -> None:
  """Best-effort in-app notification when a child job fails to enqueue."""
  # Exit early when there is no parent job to resolve the user.
  if parent_job is None:
    return

  # Require a user id so the notification can be scoped correctly.
  if not parent_job.user_id:
    return

  # Normalize the user id to guard against malformed values.
  try:
    user_id = uuid.UUID(str(parent_job.user_id))
  except ValueError:
    return

  # Dispatch an in-app notification with retry metadata.
  service = build_notification_service(settings)
  try:
    await service.notify_in_app(user_id=user_id, template_id="child_job_failed_retry_v1", data={"job_id": child_job_id, "parent_job_id": parent_job.job_id, "retry_target": child_job_id})
  except Exception as exc:  # noqa: BLE001
    logging.getLogger(__name__).error("Failed sending child job failure notification: %s", exc, exc_info=True)


def _merge_logs(*log_sets: Iterable[str]) -> Iterable[str]:
  for logs in log_sets:
    yield from logs


def _parse_timeout_env(var_name: str) -> int:
  """Parse a timeout value from the environment."""

  raw_value = os.getenv(var_name)
  if not raw_value:
    return 0
  try:
    seconds = int(raw_value)
  except ValueError as exc:  # pragma: no cover - defensive
    raise ValueError(f"{var_name} must be an integer.") from exc
  return max(0, seconds)


def _summarize_cost(usage: list[dict[str, Any]], total_cost: float) -> dict[str, Any]:
  # Roll up token counts and total cost into the job payload expected by Dylen.
  total_input_tokens = 0
  total_output_tokens = 0
  for entry in usage:
    total_input_tokens += int(entry.get("input_tokens") or entry.get("prompt_tokens") or 0)
    output_tokens = int(entry.get("output_tokens") or entry.get("completion_tokens") or 0)
    total_output_tokens += output_tokens
  return {"currency": "USD", "total_input_tokens": total_input_tokens, "total_output_tokens": total_output_tokens, "total_cost": total_cost, "calls": usage}


def _section_contains_fenster(section_payload: dict[str, Any]) -> bool:
  """Detect whether a generated section includes any fenster widgets."""
  if not isinstance(section_payload, dict):
    return False
  subsections = section_payload.get("subsections")
  if not isinstance(subsections, list):
    return False
  for subsection in subsections:
    if not isinstance(subsection, dict):
      continue
    items = subsection.get("items")
    if not isinstance(items, list):
      continue
    for item in items:
      if not isinstance(item, dict):
        continue
      item_type = str(item.get("type") or "").strip().lower()
      if item_type == "fenster":
        return True
  return False


def _extract_widget_public_ids(section_payload: dict[str, Any], *, widget_type: str) -> list[str]:
  """Collect public widget ids from subsection items for a specific widget type."""
  collected: list[str] = []
  if not isinstance(section_payload, dict):
    return collected
  subsections = section_payload.get("subsections")
  if not isinstance(subsections, list):
    return collected
  for subsection in subsections:
    if not isinstance(subsection, dict):
      continue
    items = subsection.get("items")
    if not isinstance(items, list):
      continue
    for item in items:
      if not isinstance(item, dict):
        continue
      widget_payload = item.get(widget_type)
      if isinstance(widget_payload, list) and widget_payload:
        maybe_id = widget_payload[-1]
        if isinstance(maybe_id, str) and maybe_id.strip():
          collected.append(maybe_id.strip())
      if isinstance(widget_payload, dict):
        maybe_id = widget_payload.get("id")
        if isinstance(maybe_id, str) and maybe_id.strip():
          collected.append(maybe_id.strip())
  return collected


def _extract_section_illustration_id(section_content: dict[str, Any] | None) -> int | None:
  """Return the active illustration id from section content when present."""
  if not isinstance(section_content, dict):
    return None
  illustration = section_content.get("illustration")
  if not isinstance(illustration, dict):
    return None
  raw_id = illustration.get("id")
  if raw_id is None:
    return None
  try:
    normalized_id = int(raw_id)
  except (TypeError, ValueError):
    return None
  if normalized_id <= 0:
    return None
  return normalized_id


def _derive_illustration_metadata_from_payload(payload: dict[str, Any], section_content: dict[str, Any]) -> tuple[str, str, list[str]]:
  """Build safe fallback illustration metadata for failure logging and row persistence."""
  illustration = section_content.get("illustration") if isinstance(section_content, dict) else None
  caption = ""
  ai_prompt = ""
  keywords: list[str] = []
  if isinstance(illustration, dict):
    caption = str(illustration.get("caption") or "").strip()
    ai_prompt = str(illustration.get("ai_prompt") or "").strip()
    raw_keywords = illustration.get("keywords")
    if isinstance(raw_keywords, list):
      keywords = [str(item).strip() for item in raw_keywords if str(item).strip()]

  topic = str(payload.get("topic") or "Lesson Topic").strip() or "Lesson Topic"
  section_title = str(section_content.get("section") or f"Section {payload.get('section_index') or 'Unknown'}").strip()
  markdown_payload = section_content.get("markdown")
  markdown_text = ""
  if isinstance(markdown_payload, dict):
    markdown_text = str(markdown_payload.get("markdown") or "").strip()

  if not caption:
    caption = f"{section_title} visual summary"
  if not ai_prompt:
    guidance = markdown_text[:400] if markdown_text else section_title
    ai_prompt = f"Create an educational illustration for topic '{topic}'. Focus on: {guidance}."
  if len(keywords) < 4:
    defaults = [topic, section_title, "illustration", "learning"]
    merged = [*keywords]
    for item in defaults:
      normalized = str(item).strip()
      if normalized and normalized not in merged:
        merged.append(normalized)
      if len(merged) == 4:
        break
    keywords = merged[:4]
  return caption, ai_prompt, keywords


async def _update_subsection_widget_status(*, section_id: int, widget_types: tuple[str, ...], status: str, widget_id: str | None = None, public_ids: list[str] | None = None) -> None:
  """Best-effort update for subsection widget lifecycle status after child-job completion."""
  if section_id <= 0:
    return
  if not widget_types:
    return
  session_factory = get_session_factory()
  if session_factory is None:
    return
  normalized_types = {item.strip().lower() for item in widget_types if item.strip()}
  if not normalized_types:
    return
  normalized_public_ids = {item.strip() for item in (public_ids or []) if item and item.strip()}
  try:
    async with session_factory() as session:
      stmt = select(SubsectionWidget).join(Subsection, Subsection.id == SubsectionWidget.subsection_id).where(Subsection.section_id == section_id)
      result = await session.execute(stmt)
      rows = result.scalars().all()
      changed = False
      for row in rows:
        row_widget_type = str(row.widget_type or "").strip().lower()
        if row_widget_type not in normalized_types:
          continue
        if normalized_public_ids and str(row.public_id or "").strip() not in normalized_public_ids:
          continue
        row.status = status
        if widget_id is not None:
          row.widget_id = widget_id
        session.add(row)
        changed = True
      if changed:
        await session.commit()
  except Exception:  # noqa: BLE001
    logging.getLogger(__name__).error("Failed updating subsection widget status for section_id=%s", section_id, exc_info=True)


async def _resolve_section_widget_public_id(*, section_id: int, widget_type: str) -> str | None:
  """Best-effort lookup of the first subsection widget public id for a section/widget type."""
  if section_id <= 0:
    return None
  normalized_widget_type = widget_type.strip().lower()
  if normalized_widget_type == "":
    return None
  session_factory = get_session_factory()
  if session_factory is None:
    return None
  try:
    async with session_factory() as session:
      stmt = (
        select(SubsectionWidget.public_id)
        .join(Subsection, Subsection.id == SubsectionWidget.subsection_id)
        .where(Subsection.section_id == section_id, SubsectionWidget.widget_type == normalized_widget_type, SubsectionWidget.is_archived.is_(False), Subsection.is_archived.is_(False))
        .order_by(Subsection.subsection_index.asc(), SubsectionWidget.widget_index.asc())
        .limit(1)
      )
      result = await session.execute(stmt)
      value = result.scalar_one_or_none()
      return str(value).strip() if isinstance(value, str) and value.strip() else None
  except Exception:  # noqa: BLE001
    logging.getLogger(__name__).error("Failed resolving subsection widget public id for section_id=%s widget_type=%s", section_id, normalized_widget_type, exc_info=True)
    return None


async def _resolve_fenster_widget_by_subsection_mapping(*, session: Any, section_id: int, subsection_widget_public_ids: list[str]) -> FensterWidget | None:
  """Resolve a fenster row from subsection widget mappings for the current section."""
  if section_id <= 0:
    return None
  candidate_public_ids = [str(item).strip() for item in subsection_widget_public_ids if str(item).strip()]
  if not candidate_public_ids:
    return None
  mapping_stmt = (
    select(SubsectionWidget.widget_id)
    .join(Subsection, Subsection.id == SubsectionWidget.subsection_id)
    .where(Subsection.section_id == section_id, SubsectionWidget.widget_type == "fenster", SubsectionWidget.public_id.in_(candidate_public_ids), SubsectionWidget.is_archived.is_(False), Subsection.is_archived.is_(False))
    .limit(1)
  )
  mapping_row = (await session.execute(mapping_stmt)).first()
  if mapping_row is None or mapping_row.widget_id is None:
    return None
  widget_stmt = select(FensterWidget).where(FensterWidget.public_id == str(mapping_row.widget_id)).limit(1)
  return (await session.execute(widget_stmt)).scalar_one_or_none()


async def _update_lesson_request_status(*, lesson_request_id: int | None, status: str) -> None:
  """Best-effort update for lesson request lifecycle status."""
  if lesson_request_id is None:
    return
  session_factory = get_session_factory()
  if session_factory is None:
    return
  try:
    async with session_factory() as session:
      row = await session.get(LessonRequest, int(lesson_request_id))
      if row is None:
        return
      row.status = status
      session.add(row)
      await session.commit()
  except Exception:  # noqa: BLE001
    logging.getLogger(__name__).error("Failed updating lesson_request status for lesson_request_id=%s", lesson_request_id, exc_info=True)


async def _update_section_status(*, section_id: int | None, status: str) -> None:
  """Best-effort update for section lifecycle status."""
  if section_id is None:
    return
  session_factory = get_session_factory()
  if session_factory is None:
    return
  try:
    async with session_factory() as session:
      row = await session.get(Section, int(section_id))
      if row is None:
        return
      row.status = status
      session.add(row)
      await session.commit()
  except Exception:  # noqa: BLE001
    logging.getLogger(__name__).error("Failed updating section status for section_id=%s", section_id, exc_info=True)


async def _mark_lesson_pipeline_failed(*, lesson_id: str) -> None:
  """Best-effort failure propagation for lesson and linked lesson request rows."""
  if lesson_id.strip() == "":
    return
  session_factory = get_session_factory()
  if session_factory is None:
    return
  try:
    async with session_factory() as session:
      lesson_row = await session.get(Lesson, lesson_id)
      if lesson_row is None:
        return
      lesson_row.status = "failed"
      session.add(lesson_row)
      linked_lesson_request_id = int(lesson_row.lesson_request_id) if lesson_row.lesson_request_id is not None else None
      if linked_lesson_request_id is not None:
        lesson_request_row = await session.get(LessonRequest, linked_lesson_request_id)
        if lesson_request_row is not None:
          lesson_request_row.status = "failed"
          session.add(lesson_request_row)
      await session.commit()
  except Exception:  # noqa: BLE001
    logging.getLogger(__name__).error("Failed propagating failure status for lesson_id=%s", lesson_id, exc_info=True)


def _remove_widget_items_by_public_id(*, section_payload: dict[str, Any], section_index: int, widget_type: str, public_ids: list[str]) -> list[str]:
  """Remove subsection widget items by public id and return removed widget CSV references."""
  removed_refs: list[str] = []
  if not isinstance(section_payload, dict):
    return removed_refs
  target_public_ids = {str(item).strip() for item in public_ids if str(item).strip()}
  if not target_public_ids:
    return removed_refs
  subsections = section_payload.get("subsections")
  if not isinstance(subsections, list):
    return removed_refs
  normalized_type = str(widget_type).strip()
  for subsection_position, subsection in enumerate(subsections, start=1):
    if not isinstance(subsection, dict):
      continue
    items = subsection.get("items")
    if not isinstance(items, list):
      continue
    retained_items: list[Any] = []
    for widget_position, item in enumerate(items, start=1):
      if not isinstance(item, dict):
        retained_items.append(item)
        continue
      widget_payload = item.get(normalized_type)
      if not isinstance(widget_payload, list) and not isinstance(widget_payload, dict):
        retained_items.append(item)
        continue
      widget_public_id = None
      if isinstance(widget_payload, list) and widget_payload:
        maybe_public_id = widget_payload[-1]
        if isinstance(maybe_public_id, str) and maybe_public_id.strip():
          widget_public_id = maybe_public_id.strip()
      if isinstance(widget_payload, dict):
        maybe_public_id = widget_payload.get("id")
        if isinstance(maybe_public_id, str) and maybe_public_id.strip():
          widget_public_id = maybe_public_id.strip()
      if widget_public_id not in target_public_ids:
        retained_items.append(item)
        continue
      removed_refs.append(f"{section_index}.{subsection_position}.{widget_position}.{normalized_type}")
    subsection["items"] = retained_items
  return removed_refs
