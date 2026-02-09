"""Background processor for queued lesson generation jobs."""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.ai.agents.coach import CoachAgent
from app.ai.agents.fenster_builder import FensterBuilderAgent
from app.ai.agents.illustration import IllustrationAgent
from app.ai.orchestrator import DylenOrchestrator, OrchestrationError, OrchestrationResult
from app.ai.pipeline.contracts import GenerationRequest, JobContext
from app.ai.router import get_model_for_mode
from app.ai.utils.cost import calculate_total_cost
from app.ai.utils.progress import SectionProgressUpdate
from app.api.models import GenerateLessonRequest, WritingCheckRequest
from app.config import Settings
from app.core.database import get_session_factory
from app.jobs.models import JobRecord
from app.jobs.progress import MAX_TRACKED_LOGS, JobCanceledError, JobProgressTracker, SectionProgress, build_call_plan
from app.notifications.factory import build_notification_service
from app.schema.fenster import FensterWidget, FensterWidgetType
from app.schema.illustrations import Illustration, SectionIllustration
from app.schema.lessons import Section
from app.schema.quotas import QuotaPeriod
from app.schema.service import SchemaService
from app.services.maintenance import archive_old_lessons
from app.services.model_routing import _get_orchestrator, resolve_agent_defaults
from app.services.quota_buckets import QuotaExceededError, get_quota_snapshot
from app.services.request_validation import _resolve_learner_level, _resolve_primary_language
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.section_shorthand import build_section_shorthand_content
from app.services.storage_client import build_storage_client
from app.services.tasks.factory import get_task_enqueuer
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.storage.factory import _get_repo
from app.storage.jobs_repo import JobsRepository
from app.storage.lessons_repo import LessonRecord
from app.utils.compression import compress_html
from app.utils.ids import generate_lesson_id
from app.writing.orchestrator import WritingCheckOrchestrator


class JobProcessor:
  """Coordinates execution of queued jobs."""

  def __init__(self, *, jobs_repo: JobsRepository, orchestrator: DylenOrchestrator, settings: Settings) -> None:
    self._jobs_repo = jobs_repo
    self._orchestrator = orchestrator
    self._settings = settings
    self._logger = logging.getLogger(__name__)

  async def process_job(self, job: JobRecord) -> JobRecord | None:
    """Execute a single queued job, routing by type."""
    if job.status != "queued":
      return job

    if job.target_agent == "fenster_builder":
      return await self._process_fenster_build(job)

    if job.target_agent == "coach":
      return await self._process_coach_job(job)

    if job.target_agent == "illustration":
      return await self._process_illustration_job(job)

    if job.target_agent == "maintenance":
      return await self._process_maintenance_job(job)

    if "text" in job.request and "criteria" in job.request:
      return await self._process_writing_check(job)
    return await self._process_lesson_generation(job)

  async def _process_maintenance_job(self, job: JobRecord) -> JobRecord | None:
    """Execute a background maintenance job (retention, cleanup, etc.)."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="maintenance", initial_logs=["Maintenance job acknowledged."])
    await tracker.set_phase(phase="maintenance", subphase="start")
    action = job.request.get("action")
    if not isinstance(action, str) or action.strip() == "":
      await tracker.fail(phase="failed", message="Maintenance job missing action.")
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs)
      return None
    action = action.strip().lower()
    if action != "archive_old_lessons":
      await tracker.fail(phase="failed", message="Unsupported maintenance action.")
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs)
      return None
    session_factory = get_session_factory()
    if session_factory is None:
      await tracker.fail(phase="failed", message="Database is not initialized.")
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs)
      return None
    try:
      async with session_factory() as session:
        archived_count = await archive_old_lessons(session, settings=self._settings)
      tracker.add_logs(f"Archived {archived_count} lesson(s).")
      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
      payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs, "result_json": {"action": action, "archived_count": archived_count}, "completed_at": completed_at}
      updated = await self._jobs_repo.update_job(job.job_id, **payload)
      return updated
    except Exception as exc:  # noqa: BLE001
      self._logger.error("Maintenance job failed", exc_info=True)
      await tracker.fail(phase="failed", message=f"Maintenance job failed: {exc}")
      await self._jobs_repo.update_job(job.job_id, status="error", phase="failed", progress=100.0, logs=tracker.logs)
      return None

  async def _process_fenster_build(self, job: JobRecord) -> JobRecord | None:
    """Execute Fenster Widget generation."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="fenster", initial_logs=["Fenster job picked up."])
    await tracker.set_phase(phase="building", subphase="generating_code")

    try:
      provider = self._settings.fenster_provider
      model_name = self._settings.fenster_model

      model_instance = get_model_for_mode(provider, model_name, agent="fenster_builder")

      schema_service = SchemaService()

      usage_list = []

      def usage_sink(u: dict[str, Any]) -> None:
        usage_list.append(u)

      agent = FensterBuilderAgent(model=model_instance, prov=provider, schema=schema_service, use=usage_sink)

      payload = job.request.get("payload", {})
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
      fenster_id = uuid.uuid4()
      session_factory = get_session_factory()
      if session_factory:
        async with session_factory() as session:
          widget = FensterWidget(fenster_id=fenster_id, type=FensterWidgetType.INLINE_BLOB, content=compressed, url=None)
          session.add(widget)
          await session.commit()

      # Calculate cost
      total_cost = calculate_total_cost(usage_list)
      cost_summary = _summarize_cost(usage_list, total_cost)
      await tracker.set_cost(cost_summary)

      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

      result_json = {"fenster_id": str(fenster_id)}

      payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs + ["Widget built and stored."], "result_json": result_json, "cost": cost_summary, "completed_at": completed_at}
      updated = await self._jobs_repo.update_job(job.job_id, **payload)
      return updated

    except Exception as exc:
      # Gracefully handle quota disabled or exceeded by marking success-but-skipped or just done.
      # Since we don't have a partial-success status, "done" with logs is better than "error" for quota toggles.
      if "quota disabled" in str(exc) or isinstance(exc, QuotaExceededError):
        self._logger.info("Fenster quota disabled, skipping job %s", job.job_id)
        completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs + ["Quota disabled. Skipping widget build."], "result_json": {}, "completed_at": completed_at}
        updated = await self._jobs_repo.update_job(job.job_id, **payload)
        return updated

      self._logger.error("Fenster build failed", exc_info=True)
      await tracker.fail(phase="failed", message=f"Fenster build failed: {exc}")
      payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs}
      await self._jobs_repo.update_job(job.job_id, **payload)
      return None

  async def _process_coach_job(self, job: JobRecord) -> JobRecord | None:
    """Execute Coach generation."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="coach", initial_logs=["Coach job picked up."])
    await tracker.set_phase(phase="building", subphase="generating_audio")

    try:
      # Use section_builder_provider settings as default for Coach
      provider = self._settings.section_builder_provider
      model_name = self._settings.section_builder_model

      model_instance = get_model_for_mode(provider, model_name, agent="coach")
      schema_service = SchemaService()

      usage_list = []

      def usage_sink(u: dict[str, Any]) -> None:
        usage_list.append(u)

      agent = CoachAgent(model=model_instance, prov=provider, schema=schema_service, use=usage_sink)

      payload = job.request.get("payload", {})
      # Context
      dummy_req = GenerationRequest(topic=payload.get("topic", "unknown"), depth="highlights", section_count=1)
      # Forward settings and user metadata for agent-scoped quota reservations.
      job_metadata = {"settings": self._settings}
      if job.user_id:
        job_metadata["user_id"] = str(job.user_id)
      job_ctx = JobContext(job_id=job.job_id, created_at=datetime.utcnow(), provider=provider, model=model_name or "default", request=dummy_req, metadata=job_metadata)

      audio_ids = await agent.run(payload, job_ctx)

      # Cost
      total_cost = calculate_total_cost(usage_list)
      cost_summary = _summarize_cost(usage_list, total_cost)
      await tracker.set_cost(cost_summary)

      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
      result_json = {"audio_ids": audio_ids, "count": len(audio_ids)}

      payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs + [f"Generated {len(audio_ids)} audio segments."], "result_json": result_json, "cost": cost_summary, "completed_at": completed_at}
      updated = await self._jobs_repo.update_job(job.job_id, **payload)
      return updated

    except Exception as exc:
      self._logger.error("Coach job failed", exc_info=True)
      await tracker.fail(phase="failed", message=f"Coach job failed: {exc}")
      payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs}
      await self._jobs_repo.update_job(job.job_id, **payload)
      return None

  async def _process_illustration_job(self, job: JobRecord) -> JobRecord | None:
    """Execute section illustration generation and persistence."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="illustration", initial_logs=["Illustration job picked up."])
    await tracker.set_phase(phase="building", subphase="generating_image")

    payload = job.request.get("payload", {})
    section_id = int(payload.get("section_id") or 0)
    illustration_row_id: int | None = None
    uploaded_object_name: str | None = None
    generation_caption: str | None = None
    generation_prompt: str | None = None
    generation_keywords: list[str] | None = None
    finalized_success = False

    try:
      if section_id <= 0:
        raise ValueError("Illustration job payload missing valid section_id.")

      session_factory = get_session_factory()
      if session_factory is None:
        raise RuntimeError("Database session factory unavailable.")
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
        existing_illustration_id = _extract_section_illustration_id(section_row.content)
        if existing_illustration_id is not None:
          existing_illustration = await session.get(Illustration, existing_illustration_id)
          if existing_illustration is not None and existing_illustration.status == "completed" and await storage_client.exists(existing_illustration.storage_object_name):
            total_cost = calculate_total_cost([])
            cost_summary = _summarize_cost([], total_cost)
            await tracker.set_cost(cost_summary)
            completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            result_json = {"section_id": section_id, "illustration_id": int(existing_illustration.id), "image_name": existing_illustration.storage_object_name, "skipped": True}
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
            return updated

      # Resolve runtime-configured provider/model for the illustration agent.
      runtime_config: dict[str, Any] = {}
      if job.user_id:
        try:
          parsed_user_id = uuid.UUID(str(job.user_id))
        except ValueError:
          parsed_user_id = None
        if parsed_user_id is not None:
          async with session_factory() as session:
            user = await get_user_by_id(session, parsed_user_id)
            if user is not None:
              tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
              runtime_config = await resolve_effective_runtime_config(session, settings=self._settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
      provider = str(runtime_config.get("ai.illustration.provider") or runtime_config.get("ai.visualizer.provider") or self._settings.illustration_provider)
      model_name = str(runtime_config.get("ai.illustration.model") or runtime_config.get("ai.visualizer.model") or self._settings.illustration_model or "")
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

      object_name = f"{illustration_row_id}.webp"
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
        link_row = SectionIllustration(section_id=section_id, illustration_id=illustration_row_id)
        session.add(link_row)

        # Keep section payload as source of truth for the active illustration pointer.
        section_content = dict(section_row.content or {})
        section_content["illustration"] = {"caption": generation_caption, "ai_prompt": generation_prompt, "keywords": generation_keywords, "id": illustration_row_id}
        shorthand_content = build_section_shorthand_content(section_content)
        section_row.content = section_content
        section_row.content_shorthand = shorthand_content
        session.add(section_row)
        await session.commit()
      finalized_success = True

      total_cost = calculate_total_cost(usage_list)
      cost_summary = _summarize_cost(usage_list, total_cost)
      await tracker.set_cost(cost_summary)
      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
      result_json = {"section_id": section_id, "illustration_id": illustration_row_id, "image_name": uploaded_object_name or "", "mime_type": "image/webp"}
      update_payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs + [f"Illustration generated for section {section_id}."], "result_json": result_json, "cost": cost_summary, "completed_at": completed_at}
      updated = await self._jobs_repo.update_job(job.job_id, **update_payload)
      return updated

    except Exception as exc:
      # Best-effort cleanup and state persistence so failures remain diagnosable.
      session_factory = get_session_factory()
      if session_factory is not None and not finalized_success:
        try:
          async with session_factory() as session:
            if illustration_row_id is None:
              failed_row = Illustration(
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
      await tracker.fail(phase="failed", message=f"Illustration job failed: {exc}")
      payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs}
      await self._jobs_repo.update_job(job.job_id, **payload)
      return None

  async def _process_lesson_generation(self, job: JobRecord) -> JobRecord | None:
    """Execute a single queued lesson generation job."""

    base_logs = job.logs + ["Job acknowledged by worker."]
    try:
      call_plan = build_call_plan(job.request)
    except ValueError as exc:
      error_log = f"Validation failed: {exc}"
      payload = {"status": "error", "phase": "failed", "subphase": "validation", "progress": 100.0, "logs": base_logs + [error_log]}
      await self._jobs_repo.update_job(job.job_id, **payload)
      return None

    total_steps = call_plan.total_steps(include_validation=True, include_repair=True)
    # Prefer persisted expected section counts so quota-capped jobs remain deterministic.
    expected_sections = int(job.expected_sections or call_plan.depth)
    initial_logs = base_logs + [
      f"Planned AI calls: {call_plan.required_calls}",
      f"Depth: {call_plan.depth}",
      f"Planner calls: {call_plan.planner_calls}",
      f"SectionBuilder calls: {call_plan.section_builder_calls}",
      f"Repair calls: {call_plan.repair_calls}",
    ]
    base_completed_indexes = _infer_completed_section_indexes(job)
    tracker = JobProgressTracker(
      job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=total_steps, total_ai_calls=call_plan.total_ai_calls, label_prefix=call_plan.label_prefix, initial_logs=initial_logs, completed_section_indexes=base_completed_indexes
    )
    await tracker.set_phase(phase="plan", subphase="planner_start", expected_sections=expected_sections)

    start_time = time.monotonic()

    # Re-hydrate request model for access to typed fields
    # Use internal helper to strip metadata (like _meta, user_id) that causes validation errors
    try:
      cleaned_request = _strip_internal_request_fields(job.request)
      request_model = GenerateLessonRequest.model_validate(cleaned_request)
    except ValidationError:
      self._logger.warning("Job %s has invalid request data, aborting.", job.job_id)
      raise
    soft_timeout = _parse_timeout_env("JOB_SOFT_TIMEOUT_SECONDS")
    hard_timeout = _parse_timeout_env("JOB_HARD_TIMEOUT_SECONDS")
    soft_timeout_recorded = False
    # Capture quota config for per-section consumption in the progress callback.
    # Keep quota enforcement metadata separate from agent-side reservations.
    quota_user_id: uuid.UUID | None = None
    quota_sections_per_month = 0

    async def _check_timeouts() -> bool:
      nonlocal soft_timeout_recorded
      elapsed = time.monotonic() - start_time
      if hard_timeout and elapsed >= hard_timeout:
        await tracker.fail(phase="failed", message="Job hit hard timeout.")
        return True
      if soft_timeout and elapsed >= soft_timeout and not soft_timeout_recorded:
        tracker.add_logs("Soft timeout threshold exceeded; continuing until hard timeout.")
        soft_timeout_recorded = True
      return False

    tracker.add_logs("Collect phase started.")
    try:
      if await _check_timeouts():
        return None

      # Normalize retry targeting before invoking orchestration.
      retry_agents = _normalize_retry_agents(job.retry_agents)

      if retry_agents:
        tracker.add_logs(f"Retry agents: {', '.join(sorted(retry_agents))}")

      retry_section_indexes = _normalize_retry_section_indexes(job.retry_sections, expected_sections)
      retry_section_numbers = _to_section_numbers(retry_section_indexes) if retry_section_indexes else None
      is_retry = job.retry_count is not None and job.retry_count > 0
      enable_repair = retry_agents is None or "repair" in retry_agents
      is_retry = job.retry_count is not None and job.retry_count > 0
      enable_repair = retry_agents is None or "repair" in retry_agents
      # Unused variables removed: base_result_json, base_completed_sections, retry_completed_indexes
      # Enforce quota cap for section generation, including mid-queue tier changes.
      session_factory = get_session_factory()
      # Store runtime config for model defaults once user tier is known.
      runtime_config: dict[str, Any] | None = None

      # Determine lesson_id early for persistence
      lesson_id = job.result_json.get("lesson_id") if job.result_json and "lesson_id" in job.result_json else generate_lesson_id()

      # Update job metadata with lesson_id so Orchestrator can persist sections incrementally
      # We'll construct full job_metadata below.
      if session_factory is not None and job.user_id:
        try:
          quota_user_id = uuid.UUID(str(job.user_id))
        except ValueError:
          quota_user_id = None
        if quota_user_id is not None:
          try:
            async with session_factory() as session:
              user = await get_user_by_id(session, quota_user_id)
              if user is not None:
                tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
                runtime_config = await resolve_effective_runtime_config(session, settings=self._settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
                quota_sections_per_month = int(runtime_config.get("limits.sections_per_month") or 0)
                if quota_sections_per_month <= 0:
                  raise QuotaExceededError("section.generate quota disabled")
                quota_snapshot = await get_quota_snapshot(session, user_id=user.id, metric_key="section.generate", period=QuotaPeriod.MONTH, limit=quota_sections_per_month)
                if quota_snapshot.remaining <= 0:
                  raise QuotaExceededError("section.generate quota exceeded")
                # Respect any persisted cap plus the live remaining quota to avoid overruns.
                expected_sections = min(int(expected_sections), int(quota_snapshot.remaining))
                if expected_sections <= 0:
                  raise QuotaExceededError("section.generate quota exceeded")
          except Exception as exc:  # noqa: BLE001
            if isinstance(exc, QuotaExceededError):
              raise
            raise ValueError(f"Quota enforcement failed: {exc}") from exc

      if retry_section_indexes:
        tracker.add_logs(f"Retry sections: {', '.join(str(i) for i in retry_section_indexes)}")

      # Cap generation to the first N sections when expected_sections is lower than the plan depth.
      quota_section_filter = None
      if expected_sections < call_plan.depth:
        quota_section_filter = set(range(1, expected_sections + 1))
        tracker.add_logs(f"Quota cap applied: generating only {expected_sections} section(s) this month.")

      effective_section_filter = retry_section_numbers
      if quota_section_filter is not None:
        effective_section_filter = quota_section_filter if effective_section_filter is None else set(effective_section_filter).intersection(quota_section_filter)
        if effective_section_filter is not None and len(effective_section_filter) == 0:
          raise ValueError("No sections remain eligible for generation under the current quota cap.")

      # -------------------------------------------------------------------------
      # RETRY LOGIC: DB-BASED PRE-CHECK
      # -------------------------------------------------------------------------
      if is_retry:
        try:
          repo = _get_repo(self._settings)
          # If we are retrying, the lesson might already exist.
          # lesson_id is already resolved above.
          existing_sections = await repo.list_sections(lesson_id)
          if existing_sections:
            completed_indices = {s.order_index for s in existing_sections}  # 0-based
            # We need to generate everything from 0 to expected_sections-1 that is NOT in existing_indices
            needed_indices = {i for i in range(expected_sections) if i not in completed_indices}

            # Convert to 1-based for Orchestraor filter
            needed_section_numbers = {i + 1 for i in needed_indices}

            if effective_section_filter:
              effective_section_filter = effective_section_filter.intersection(needed_section_numbers)
            else:
              effective_section_filter = needed_section_numbers

            tracker.add_logs(f"Retry: Found {len(existing_sections)} sections. Generating: {sorted(effective_section_filter)}")
          else:
            tracker.add_logs("Retry: No existing sections found in DB. Generating all.")
        except Exception as exc:
          self._logger.error("Failed to check existing sections for retry: %s", exc)
      # -------------------------------------------------------------------------

      # Prepare Metadata including lesson_id
      job_metadata = {"settings": self._settings, "lesson_id": lesson_id}
      if job.user_id:
        job_metadata["user_id"] = str(job.user_id)

      # Create or Ensure Lesson Record Exists (Status: Generating)
      try:
        repo = _get_repo(self._settings)
        existing_lesson = await repo.get_lesson(lesson_id)
        if not existing_lesson:
          placeholder_record = LessonRecord(
            lesson_id=lesson_id,
            user_id=str(job.user_id) if job.user_id else None,
            topic=job.request.get("topic", "Unknown"),
            title=job.request.get("topic", "Unknown"),
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            schema_version=self._settings.schema_version,
            prompt_version=self._settings.prompt_version,
            provider_a="pending",
            model_a="pending",
            provider_b="pending",
            model_b="pending",
            status="generating",
            latency_ms=0,
          )
          await repo.upsert_lesson(placeholder_record)
      except Exception as exc:
        self._logger.warning("Failed to create/check lesson record: %s", exc)

      orchestration_result = await self._run_orchestration(
        job.job_id,
        job.request,
        expected_sections=expected_sections,
        tracker=tracker,
        timeout_checker=_check_timeouts,
        retry_section_numbers=effective_section_filter,
        is_retry=is_retry,
        enable_repair=enable_repair,
        base_completed_sections=job.request.get("base_completed_sections", 0),
        retry_completed_indexes=[],  # Always start fresh for retries
        runtime_config=runtime_config,
        quota_user_id=quota_user_id,
        quota_sections_per_month=quota_sections_per_month,
        job_metadata=job_metadata,
      )

      # Abort quickly if a cancellation lands after orchestration completes.

      # Abort quickly if a cancellation lands after orchestration completes.
      canceled_record = await self._jobs_repo.get_job(job.job_id)

      if canceled_record and canceled_record.status == "canceled":
        raise JobCanceledError(f"Job {job.job_id} was canceled before validation.")

      if await _check_timeouts():
        return None

      # Surface orchestration logs even when validation fails.
      # Surface orchestration logs even when validation fails.
      tracker.extend_logs(orchestration_result.logs)

      cost_summary = _summarize_cost(orchestration_result.usage, orchestration_result.total_cost)
      await tracker.set_cost(cost_summary)

      # Finalize Lesson Record (Status: OK, Plan: Saved)
      repo = _get_repo(self._settings)

      existing_lesson = await repo.get_lesson(lesson_id)

      # extracted_plan removed (unused)

      latency_ms = int((time.monotonic() - start_time) * 1000)

      # Determine final title
      final_title = job.request.get("topic")
      if existing_lesson and existing_lesson.title:
        final_title = existing_lesson.title

      final_lesson_record = LessonRecord(
        lesson_id=lesson_id,
        user_id=str(job.user_id) if job.user_id else None,
        topic=request_model.topic,
        title=final_title,
        created_at=existing_lesson.created_at if existing_lesson else time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        schema_version=request_model.schema_version or self._settings.schema_version,
        prompt_version=self._settings.prompt_version,
        provider_a=orchestration_result.provider_a,
        model_a=orchestration_result.model_a,
        provider_b=orchestration_result.provider_b,
        model_b=orchestration_result.model_b,
        status="ok",
        latency_ms=latency_ms,
        idempotency_key=request_model.idempotency_key,
        lesson_plan=orchestration_result.artifacts.get("plan") if orchestration_result.artifacts else None,
      )
      # Save Sections logic removed - handled by SectionBuilder

      # Save Lesson Record
      await repo.upsert_lesson(final_lesson_record)

      # Notify the job owner
      await _notify_job_lesson_generated(settings=self._settings, job_request=job.request, lesson_id=lesson_id, topic=request_model.topic)

      log_updates = tracker.logs[-MAX_TRACKED_LOGS:]
      log_updates.append("Job completed successfully.")
      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

      # Re-fetch sections to report accurate count
      final_sections = await repo.list_sections(lesson_id)

      summary = {"lesson_id": lesson_id, "title": final_title, "total_sections": len(final_sections), "generated_count": len(final_sections), "sections": [{"section_id": s.section_id, "title": s.title} for s in final_sections]}

      payload = {
        "status": "done",
        "phase": "validate",
        "subphase": "complete",
        "progress": 100.0,
        "logs": log_updates,
        "result_json": summary,
        "artifacts": orchestration_result.artifacts,
        "validation": {"ok": True, "errors": []},
        "cost": cost_summary,
        "expected_sections": expected_sections,
        "completed_sections": len(final_sections),
        "completed_at": completed_at,
      }
      updated = await self._jobs_repo.update_job(job.job_id, **payload)
      return updated
    except JobCanceledError:
      # Re-fetch the record to ensure we have the final canceled state
      return await self._jobs_repo.get_job(job.job_id)

    except OrchestrationError as exc:
      # Preserve pipeline logs when orchestration fails fast.
      tracker.extend_logs(exc.logs)
      quota_metric = _extract_quota_metric(str(exc))
      if quota_metric is not None:
        quota_message = f"Quota exceeded during lesson job execution ({quota_metric})."
        self._logger.warning("Job %s failed due to exhausted quota. metric=%s error=%s", job.job_id, quota_metric, exc)
        await tracker.fail(phase="failed", message=quota_message)
        payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs}
        await self._jobs_repo.update_job(job.job_id, **payload)
        await _notify_job_failed(settings=self._settings, job=job)
        return None
      error_log = f"Job failed: {exc}"
      self._logger.error(error_log)
      await tracker.fail(phase="failed", message=error_log)
      payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs}
      await self._jobs_repo.update_job(job.job_id, **payload)
      await _notify_job_failed(settings=self._settings, job=job)
      return None

    except QuotaExceededError as exc:
      quota_metric = _extract_quota_metric(str(exc)) or "unknown"
      quota_message = f"Quota exceeded during lesson job execution ({quota_metric})."
      self._logger.warning("Job %s failed due to exhausted quota. metric=%s error=%s", job.job_id, quota_metric, exc)
      await tracker.fail(phase="failed", message=quota_message)
      payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs}
      await self._jobs_repo.update_job(job.job_id, **payload)
      await _notify_job_failed(settings=self._settings, job=job)
      return None

    except Exception as exc:  # noqa: BLE001
      error_log = f"Job failed: {exc}"
      self._logger.error("Job processing failed unexpectedly", exc_info=True)
      await tracker.fail(phase="failed", message=error_log)
      payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs}
      await self._jobs_repo.update_job(job.job_id, **payload)
      await _notify_job_failed(settings=self._settings, job=job)
      return None

  async def _process_writing_check(self, job: JobRecord) -> JobRecord | None:
    """Execute a background writing task evaluation."""
    tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="check", initial_logs=["Writing check acknowledged."])
    await tracker.set_phase(phase="evaluating", subphase="ai_check")

    try:
      # Validate and hydrate the request so inputs remain strict.
      cleaned_request = _strip_internal_request_fields(job.request)
      request_model = WritingCheckRequest.model_validate(cleaned_request)
      # Resolve writing defaults from runtime config when possible.
      runtime_config: dict[str, Any] = {}
      session_factory = get_session_factory()
      if session_factory is not None and job.user_id:
        try:
          parsed_user_id = uuid.UUID(str(job.user_id))
        except ValueError:
          parsed_user_id = None
        if parsed_user_id is not None:
          async with session_factory() as session:
            user = await get_user_by_id(session, parsed_user_id)
            if user is not None:
              tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
              runtime_config = await resolve_effective_runtime_config(session, settings=self._settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)

      provider = str(runtime_config.get("ai.writing.provider") or self._settings.writing_provider)
      model_name = str(runtime_config.get("ai.writing.model") or self._settings.writing_model or "")
      orchestrator = WritingCheckOrchestrator(provider=provider, model=model_name or None)
      result = await orchestrator.check_response(text=request_model.text, criteria=request_model.criteria)

      tracker.extend_logs(result.logs)
      cost_summary = _summarize_cost(result.usage, result.total_cost)
      await tracker.set_cost(cost_summary)
      completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
      result_json = {"ok": result.ok, "issues": result.issues, "feedback": result.feedback}
      payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs, "result_json": result_json, "cost": cost_summary, "completed_at": completed_at}
      updated = await self._jobs_repo.update_job(job.job_id, **payload)
      return updated
    except JobCanceledError:
      return await self._jobs_repo.get_job(job.job_id)

    except Exception as exc:
      self._logger.error("Writing check processing failed", exc_info=True)
      await tracker.fail(phase="failed", message=f"Writing check failed: {exc}")
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

  async def _run_orchestration(
    self,
    job_id: str,
    request: dict[str, Any],
    *,
    expected_sections: int,
    tracker: JobProgressTracker | None = None,
    timeout_checker: Callable[[], Awaitable[bool]] | None = None,
    retry_section_numbers: set[int] | None = None,
    is_retry: bool = False,
    enable_repair: bool = True,
    base_completed_sections: int = 0,
    retry_completed_indexes: list[int] | None = None,
    job_metadata: dict[str, Any] | None = None,
    runtime_config: dict[str, Any] | None = None,
    quota_user_id: uuid.UUID | None = None,
    quota_sections_per_month: int = 0,
  ) -> OrchestrationResult:
    """Execute the orchestration pipeline with guarded parameters."""

    try:
      # Drop deprecated fields so legacy records can still be parsed.
      if "mode" in request:
        request = {key: value for key, value in request.items() if key != "mode"}

      request_model = GenerateLessonRequest.model_validate(_strip_internal_request_fields(request))

    except ValidationError as exc:
      raise ValueError("Stored job request is invalid.") from exc
    topic = request_model.topic

    if len(topic) > self._settings.max_topic_length:
      raise ValueError(f"Topic exceeds max length of {self._settings.max_topic_length}.")

    # Resolve per-agent defaults so queued jobs honor runtime configuration.
    selection = resolve_agent_defaults(self._settings, runtime_config or {})
    (section_builder_provider, section_builder_model, planner_provider, planner_model, repairer_provider, repairer_model) = selection
    language = _resolve_primary_language(request_model)
    learner_level = _resolve_learner_level(request_model)
    schema_version = request_model.schema_version or self._settings.schema_version

    orchestrator = _get_orchestrator(
      self._settings, section_builder_provider=section_builder_provider, section_builder_model=section_builder_model, planner_provider=planner_provider, planner_model=planner_model, repair_provider=repairer_provider, repair_model=repairer_model
    )

    logs: list[str] = [
      f"Starting job {job_id}",
      f"Topic: {topic[:80]}{'...' if len(topic) > 80 else ''}",
      f"SectionBuilder provider: {section_builder_provider}",
      f"SectionBuilder model: {section_builder_model or 'default'}",
      f"Planner provider: {planner_provider}",
      f"Planner model: {planner_model or 'default'}",
      f"Repairer provider: {repairer_provider}",
      f"Repairer model: {repairer_model or 'default'}",
    ]

    Msgs = list[str] | None  # noqa: N806

    async def _progress_callback(phase: str, subphase: str | None, messages: Msgs = None, advance: bool = True, partial_json: dict[str, Any] | None = None, section_progress: SectionProgressUpdate | None = None) -> None:
      if tracker is None:
        return

      # Active guardrail check
      if timeout_checker and await timeout_checker():
        # Note: We can't easily raise an exception here that Orchestrator will catch nicely,
        # but Orchestrator has its own try/except now.
        # If we raise here, Orchestrator will catch it and return partial usage.
        raise TimeoutError("Job hit timeout during orchestration.")

      # Check for cancellation
      # note: dropped synchronous cancellation check to avoid async issues in callback
      # record = await self._jobs_repo.get_job(job_id)
      # if record and record.status == "canceled":
      #   raise JobCanceledError(f"Job {job_id} was canceled during orchestration.")

      # Map orchestrator section updates into tracker-friendly metadata.
      tracker_section: SectionProgress | None = None

      if section_progress is not None:
        merged_completed_sections = (section_progress.completed_sections or 0) + base_completed_sections
        tracker_section = SectionProgress(index=section_progress.index, title=section_progress.title, status=section_progress.status, retry_count=section_progress.retry_count, completed_sections=merged_completed_sections)

        # Keep track of completed retry indexes for partial merge payloads.
        if retry_completed_indexes is not None and section_progress.status == "completed":
          if section_progress.index not in retry_completed_indexes:
            retry_completed_indexes.append(section_progress.index)
        # Section quota reservations are handled inside agents to keep accounting local.

      log_message = "; ".join(messages or [])
      # merged_partial removed (unused)

      if advance:
        await tracker.complete_step(phase=phase, subphase=subphase, message=log_message or None, result_json=partial_json, expected_sections=expected_sections, section_progress=tracker_section)
      else:
        if log_message:
          tracker.add_logs(log_message)

        await tracker.set_phase(phase=phase, subphase=subphase, result_json=partial_json, expected_sections=expected_sections, section_progress=tracker_section)

    async def _job_creator(target_agent: str, payload: dict[str, Any]) -> None:
      # Fetch parent metadata so child jobs inherit the user id.
      parent_record = await self._jobs_repo.get_job(job_id)
      parent_user_id = parent_record.user_id if parent_record is not None else None
      parent_artifacts = dict(parent_record.artifacts or {}) if parent_record is not None else None
      child_jobs = list(parent_artifacts.get("child_jobs") or []) if parent_artifacts is not None else []
      new_job_id = str(uuid.uuid4())
      timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
      request = {"payload": payload, "_meta": {"parent_job_id": job_id}}
      record = JobRecord(job_id=new_job_id, user_id=parent_user_id, request=request, status="queued", target_agent=target_agent, created_at=timestamp, updated_at=timestamp, phase="queued", logs=[])
      await self._jobs_repo.create_job(record)
      # Track child jobs in the parent artifacts so the UI can retry them.
      if parent_artifacts is not None:
        child_jobs.append({"job_id": new_job_id, "target_agent": target_agent, "status": "queued"})
        parent_artifacts["child_jobs"] = child_jobs
        await self._jobs_repo.update_job(job_id, artifacts=parent_artifacts)
      # Enqueue the child job immediately so it executes without manual intervention.
      enqueuer = get_task_enqueuer(self._settings)
      try:
        await enqueuer.enqueue(new_job_id, {})
      except Exception:  # noqa: BLE001
        await self._jobs_repo.update_job(new_job_id, status="error", phase="error", logs=["Enqueue failed: CHILD_TASK_ENQUEUE_FAILED"])
        if parent_artifacts is not None:
          updated_child_jobs = []
          for child in child_jobs:
            if child.get("job_id") == new_job_id:
              updated_child_jobs.append({"job_id": new_job_id, "target_agent": target_agent, "status": "error"})
            else:
              updated_child_jobs.append(child)
          parent_artifacts["child_jobs"] = updated_child_jobs
          await self._jobs_repo.update_job(job_id, artifacts=parent_artifacts)
        await _notify_child_job_failed(settings=self._settings, parent_job=parent_record, child_job_id=new_job_id)

    # Forward settings and user metadata so agents can reserve quota locally.
    # Merge with provided job_metadata (containing lesson_id) or start fresh
    combined_metadata = dict(job_metadata or {})
    combined_metadata.setdefault("settings", self._settings)
    if quota_user_id is not None:
      combined_metadata["user_id"] = str(quota_user_id)
    result = await orchestrator.generate_lesson(
      job_id=job_id,
      topic=topic,
      details=request_model.details,
      outcomes=request_model.outcomes,
      blueprint=request_model.blueprint,
      teaching_style=request_model.teaching_style,
      learner_level=learner_level,
      depth=request_model.depth,
      widgets=request_model.widgets,
      schema_version=schema_version,
      section_builder_model=section_builder_model,
      structured_output=True,
      language=language,
      progress_callback=_progress_callback,
      section_filter=retry_section_numbers,
      enable_repair=enable_repair,
      job_creator=_job_creator,
      job_metadata=combined_metadata,
    )

    merged_logs = list(_merge_logs(logs, result.logs))

    if tracker is not None:
      await tracker.set_phase(phase="validate", subphase="validation", expected_sections=expected_sections)

    return OrchestrationResult(
      # lesson_json used to be here
      provider_a=result.provider_a,
      model_a=result.model_a,
      provider_b=result.provider_b,
      model_b=result.model_b,
      validation_errors=result.validation_errors,
      logs=merged_logs,
      usage=result.usage,
      total_cost=result.total_cost,
      artifacts=result.artifacts,
    )


def _strip_internal_request_fields(request: dict[str, Any]) -> dict[str, Any]:
  """Drop internal-only metadata keys from stored job payloads before validation."""
  # Stored job requests may include internal metadata (e.g. _meta) that must not violate strict request models.
  cleaned = {key: value for key, value in request.items() if not key.startswith("_")}

  # Drop deprecated model override fields so legacy jobs can still validate.
  cleaned.pop("models", None)
  cleaned.pop("checker_model", None)

  return cleaned


def _extract_quota_metric(error_message: str) -> str | None:
  """Extract a known quota metric name from an error message."""
  lowered = error_message.lower()
  known_metrics = ("lesson.generate", "section.generate", "coach.generate", "fenster.widget.generate", "writing.check", "ocr.extract", "image.generate")
  for metric in known_metrics:
    # Match explicit metric names so job logs can report the exact exhausted resource.
    if metric in lowered:
      return metric
  if "quota" in lowered:
    return "unknown"
  return None


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


_ALLOWED_RETRY_AGENTS = {"planner", "gatherer", "structurer", "repair"}


def _normalize_retry_agents(raw_agents: list[str] | None) -> set[str] | None:
  """Normalize retry agent names for downstream orchestration controls."""

  if not raw_agents:
    return None

  # Normalize agent names for consistency in retry logic.
  normalized = {agent.strip().lower() for agent in raw_agents if agent.strip()}
  unknown = sorted(normalized - _ALLOWED_RETRY_AGENTS)

  if unknown:
    raise ValueError(f"Unsupported retry agents: {', '.join(unknown)}")

  return normalized


def _normalize_retry_section_indexes(raw_sections: list[int] | None, expected_sections: int) -> list[int] | None:
  """Normalize 0-based retry section indexes with bounds validation."""

  if raw_sections is None:
    return None

  # Deduplicate and sort while ensuring indexes are within bounds.
  unique = sorted(set(raw_sections))
  invalid = [index for index in unique if index < 0 or index >= expected_sections]

  if invalid:
    raise ValueError("Retry section indexes are out of range.")

  return unique


def _to_section_numbers(indexes: list[int]) -> set[int]:
  """Convert 0-based indexes into 1-based section numbers."""
  # Orchestrator expects section numbers (1-based) rather than indexes.
  return {index + 1 for index in indexes}


def _infer_completed_section_indexes(record: JobRecord) -> list[int]:
  """Infer completed section indexes when explicit tracking is missing."""

  if record.completed_section_indexes:
    return list(record.completed_section_indexes)

  # Fall back to result_json length when explicit indexes are unavailable.
  if record.result_json:
    blocks = record.result_json.get("blocks")
    if isinstance(blocks, list):
      return list(range(len(blocks)))

  # Use completed_sections as a last resort when other data is missing.
  count = record.completed_sections or 0
  return list(range(count))
