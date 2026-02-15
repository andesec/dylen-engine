import logging
import time
import uuid
from typing import Any

from app.api.models import ChildJobStatus, JobCreateRequest, JobCreateResponse, JobRetryRequest, JobStatusResponse
from app.config import Settings
from app.core.database import get_session_factory
from app.jobs.models import JobKind, JobRecord
from app.schema.illustrations import Illustration
from app.schema.jobs import Job
from app.schema.lessons import Section, Subsection, SubsectionWidget
from app.schema.quotas import QuotaPeriod
from app.schema.tutor import Tutor
from app.services.quota_buckets import get_quota_snapshot
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.storage_client import build_storage_client
from app.services.tasks.factory import get_task_enqueuer
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id
from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_JOB_NOT_FOUND_MSG = "Job not found."
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_LESSON_RESUMABLE_AGENTS = {"planner", "section_builder", "tutor", "fenster_builder", "illustration"}
_COMPATIBLE_TARGETS: dict[JobKind, set[str]] = {"lesson": set(_LESSON_RESUMABLE_AGENTS), "research": {"research"}, "youtube": {"youtube"}, "maintenance": {"maintenance"}, "writing": {"writing"}, "system": {"maintenance"}}
_TARGET_METRICS: dict[str, tuple[str, str, QuotaPeriod]] = {
  "planner": ("limits.lessons_per_week", "lesson.generate", QuotaPeriod.WEEK),
  "section_builder": ("limits.sections_per_month", "section.generate", QuotaPeriod.MONTH),
  "tutor": ("limits.tutor_sections_per_month", "tutor.generate", QuotaPeriod.MONTH),
  "fenster_builder": ("limits.fenster_widgets_per_month", "fenster.widget.generate", QuotaPeriod.MONTH),
  "illustration": ("limits.image_generations_per_month", "image.generate", QuotaPeriod.MONTH),
  "writing": ("limits.writing_checks_per_month", "writing.check", QuotaPeriod.MONTH),
  "ocr": ("limits.ocr_files_per_month", "ocr.extract", QuotaPeriod.MONTH),
}


def _expected_sections_from_payload(payload: dict[str, Any], target_agent: str) -> int:
  if target_agent != "planner":
    return 0
  # Try section_count first (new field), fallback to depth mapping for backward compatibility
  section_count = payload.get("section_count")
  if section_count is not None:
    return int(section_count)
  # Legacy depth mapping
  depth = str(payload.get("depth") or "highlights").strip().lower()
  mapping = {"highlights": 2, "detailed": 4, "training": 5}
  return int(mapping.get(depth, 2))


def _job_status_from_record(
  record: JobRecord, *, child_jobs: list[ChildJobStatus] | None = None, requested_job_id: str | None = None, resolved_job_id: str | None = None, superseded_job_id: str | None = None, follow_from_job_id: str | None = None
) -> JobStatusResponse:
  return JobStatusResponse(
    job_id=record.job_id,
    status=record.status,
    child_jobs=child_jobs,
    lesson_id=record.lesson_id,
    requested_job_id=requested_job_id,
    resolved_job_id=resolved_job_id or record.job_id,
    was_superseded=bool(requested_job_id and requested_job_id != record.job_id),
    superseded_by_job_id=record.superseded_by_job_id,
    superseded_job_id=superseded_job_id,
    follow_from_job_id=follow_from_job_id,
  )


def _normalize_retry_section_filters(*, requested_sections: list[int] | None, checkpoints: list[Any]) -> set[int] | None:
  if not requested_sections:
    return None
  requested = {int(item) for item in requested_sections}
  checkpoint_indexes = {int(item.section_index) for item in checkpoints if item.section_index is not None}
  if not checkpoint_indexes:
    return requested
  if requested.intersection(checkpoint_indexes):
    return requested
  # Existing retry endpoint historically accepted 0-based indexes while section checkpoints use 1-based order_index.
  shifted = {int(item) + 1 for item in requested}
  if shifted.intersection(checkpoint_indexes):
    return shifted
  return requested


async def _apply_in_place_retry_filters(*, repo: Any, record: JobRecord, payload: JobRetryRequest) -> None:
  list_checkpoints_fn = getattr(repo, "list_checkpoints", None)
  upsert_checkpoint_fn = getattr(repo, "upsert_checkpoint", None)
  if not callable(list_checkpoints_fn) or not callable(upsert_checkpoint_fn):
    return
  checkpoints = await list_checkpoints_fn(job_id=record.job_id)
  if not checkpoints:
    return
  requested_agents = {str(item) for item in (payload.agents or [])}
  requested_sections = _normalize_retry_section_filters(requested_sections=payload.sections, checkpoints=checkpoints)
  explicit_filters = bool(payload.agents or payload.sections)
  for checkpoint in checkpoints:
    stage = str(checkpoint.stage)
    section_index = int(checkpoint.section_index) if checkpoint.section_index is not None else None
    if requested_agents and stage not in requested_agents:
      continue
    if requested_sections is not None and section_index is not None and section_index not in requested_sections:
      continue
    if explicit_filters:
      next_state = "pending"
    else:
      current_state = str(checkpoint.state)
      if current_state in {"done", "skipped"}:
        continue
      next_state = "pending"
    await upsert_checkpoint_fn(job_id=record.job_id, stage=stage, section_index=section_index, state=next_state, artifact_refs_json=checkpoint.artifact_refs_json, attempt_count=int(checkpoint.attempt_count), last_error=None)


async def _infer_resume_scope_from_source(*, source: JobRecord) -> tuple[list[int] | None, list[str] | None]:
  """Infer the narrowest resume scope from a failed source job."""
  target_agent = str(source.target_agent or "").strip()
  if target_agent not in _LESSON_RESUMABLE_AGENTS:
    return None, None
  inferred_agents = [target_agent]
  if target_agent == "planner":
    return None, inferred_agents
  wrapped_payload = source.request.get("payload") if isinstance(source.request.get("payload"), dict) else source.request
  for key in ("section_number", "section_index"):
    raw_value = wrapped_payload.get(key)
    if raw_value is None:
      continue
    try:
      section_index = int(raw_value)
    except (TypeError, ValueError):
      continue
    if section_index > 0:
      return [section_index], inferred_agents
  if source.section_id is not None:
    session_factory = get_session_factory()
    if session_factory is not None:
      async with session_factory() as session:
        section_row = await session.get(Section, int(source.section_id))
        if section_row is not None:
          return [int(section_row.order_index)], inferred_agents
  return None, inferred_agents


async def _resolve_latest_record(record: JobRecord, settings: Settings) -> JobRecord:
  repo = _get_jobs_repo(settings)
  current = record
  visited = {current.job_id}
  while current.superseded_by_job_id:
    next_job_id = str(current.superseded_by_job_id)
    if next_job_id in visited:
      break
    visited.add(next_job_id)
    next_record = await repo.get_job(next_job_id)
    if next_record is None:
      break
    current = next_record
  return current


async def _resolve_child_jobs(record: JobRecord, settings: Settings) -> list[ChildJobStatus] | None:
  repo = _get_jobs_repo(settings)
  children = await repo.list_child_jobs(parent_job_id=record.job_id, include_done=False)
  if not children:
    return None
  return [ChildJobStatus(job_id=child.job_id, status=child.status) for child in children]


async def _ensure_quota_available(db_session: AsyncSession, *, settings: Settings, user_id: str | None, target_agent: str) -> None:
  if db_session is None:
    return
  if target_agent not in _TARGET_METRICS:
    return
  if user_id is None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user id.")
  metric_limit_key, metric_key, metric_period = _TARGET_METRICS[target_agent]
  try:
    parsed_user_id = uuid.UUID(str(user_id))
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc
  user = await get_user_by_id(db_session, parsed_user_id)
  if user is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
  tier_id, _tier_name = await get_user_subscription_tier(db_session, user.id)
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
  limit = int(runtime_config.get(metric_limit_key) or 0)
  if limit <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": metric_key})
  snapshot = await get_quota_snapshot(db_session, user_id=user.id, metric_key=metric_key, period=metric_period, limit=limit)
  if snapshot.remaining <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": metric_key})


async def create_job(request: JobCreateRequest, settings: Settings, background_tasks: BackgroundTasks, db_session: AsyncSession, *, user_id: str | None = None) -> JobCreateResponse:
  if user_id is None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  compatible_targets = _COMPATIBLE_TARGETS.get(request.job_kind, set())
  if request.target_agent not in compatible_targets:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_agent is not valid for job_kind.")
  await _ensure_quota_available(db_session, settings=settings, user_id=user_id, target_agent=request.target_agent)
  auto_process = True
  if db_session is not None:
    try:
      parsed_user_id = uuid.UUID(str(user_id))
    except ValueError:
      parsed_user_id = None
    user = await get_user_by_id(db_session, parsed_user_id) if parsed_user_id is not None else None
    tier_id = None
    if user:
      tier_id, _ = await get_user_subscription_tier(db_session, user.id)
    runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=user.org_id if user else None, subscription_tier_id=tier_id, user_id=None)
    auto_process = bool(runtime_config.get("jobs.auto_process", True))
  repo = _get_jobs_repo(settings)
  existing = await repo.find_by_user_kind_idempotency_key(user_id=user_id, job_kind=request.job_kind, idempotency_key=request.idempotency_key)
  if existing is not None:
    return JobCreateResponse(job_id=existing.job_id, expected_sections=_expected_sections_from_payload(existing.request, str(existing.target_agent or "")))
  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  record = JobRecord(
    job_id=job_id,
    root_job_id=job_id,
    user_id=user_id,
    job_kind=request.job_kind,
    request=request.payload,
    status="queued",
    parent_job_id=request.parent_job_id,
    lesson_id=request.lesson_id,
    section_id=request.section_id,
    target_agent=request.target_agent,
    logs=["Job queued."],
    result_json=None,
    error_json=None,
    created_at=timestamp,
    updated_at=timestamp,
    completed_at=None,
    idempotency_key=request.idempotency_key,
  )
  await repo.create_job(record)
  trigger_job_processing(background_tasks, job_id, settings, auto_process=auto_process)
  return JobCreateResponse(job_id=job_id, expected_sections=_expected_sections_from_payload(request.payload, request.target_agent))


async def retry_job(job_id: str, payload: JobRetryRequest, settings: Settings, background_tasks: BackgroundTasks, user_id: str | None = None) -> JobStatusResponse:
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  if user_id and record.user_id != user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  if record.status not in ("error", "canceled"):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed or canceled jobs can be retried.")
  await _apply_in_place_retry_filters(repo=repo, record=record, payload=payload)
  updated = await repo.update_job(job_id, status="queued", completed_at=None, error_json=None, logs=["Manual retry queued."])
  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  trigger_job_processing(background_tasks, updated.job_id, settings, auto_process=True)
  child_jobs = await _resolve_child_jobs(updated, settings)
  return _job_status_from_record(updated, child_jobs=child_jobs, requested_job_id=job_id, resolved_job_id=updated.job_id)


async def resume_job_from_failure_admin(*, job_id: str, settings: Settings, background_tasks: BackgroundTasks, sections: list[int] | None, agents: list[str] | None) -> JobStatusResponse:
  repo = _get_jobs_repo(settings)
  source = await repo.get_job(job_id)
  if source is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  if source.status not in {"error", "canceled"}:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed or canceled jobs can be resumed.")
  if str(source.job_kind) != "lesson" or str(source.target_agent or "") not in _LESSON_RESUMABLE_AGENTS:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resume-from-failure supports lesson pipeline jobs only.")
  if sections is not None or agents is not None:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resume filters are not supported. Provide only job_id to resume the failed agent job.")
  inferred_sections, inferred_agents = await _infer_resume_scope_from_source(source=source)
  effective_sections = inferred_sections
  effective_agents = inferred_agents
  session_factory = get_session_factory()
  if session_factory is not None:
    async with session_factory() as session:
      existing_resume = (await session.execute(select(Job.job_id).where(Job.resume_source_job_id == source.job_id, Job.status.in_(("queued", "running"))).order_by(Job.created_at.desc()).limit(1))).scalar_one_or_none()
    if existing_resume is not None:
      raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Active resume job already exists: {existing_resume}")
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  resume_job_id = generate_job_id()
  resume_request = dict(source.request or {})
  if effective_sections is not None:
    resume_request["_resume_sections"] = [int(item) for item in effective_sections]
  if effective_agents is not None:
    resume_request["_resume_agents"] = [str(item) for item in effective_agents]
  resumed = JobRecord(
    job_id=resume_job_id,
    root_job_id=str(source.root_job_id or source.job_id),
    user_id=source.user_id,
    job_kind=source.job_kind,
    request=resume_request,
    status="queued",
    parent_job_id=source.parent_job_id,
    resume_source_job_id=source.job_id,
    lesson_id=source.lesson_id,
    section_id=source.section_id,
    target_agent=source.target_agent,
    logs=[f"Resumed from failed job {source.job_id}."],
    created_at=timestamp,
    updated_at=timestamp,
    idempotency_key=f"resume:{source.job_id}:{resume_job_id}",
  )
  try:
    await repo.create_job(resumed)
  except IntegrityError as exc:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Active resume job already exists for this source job.") from exc
  await repo.update_job(source.job_id, status="superseded", superseded_by_job_id=resume_job_id, completed_at=timestamp, logs=[f"Job superseded by resume job {resume_job_id}."])
  await _seed_resume_checkpoints(job=resumed, settings=settings, section_filters=effective_sections, agent_filters=effective_agents)
  trigger_job_processing(background_tasks, resume_job_id, settings, auto_process=True)
  child_jobs = await _resolve_child_jobs(resumed, settings)
  return _job_status_from_record(resumed, child_jobs=child_jobs, requested_job_id=job_id, resolved_job_id=resume_job_id, superseded_job_id=source.job_id, follow_from_job_id=resume_job_id)


async def _seed_resume_checkpoints(*, job: JobRecord, settings: Settings, section_filters: list[int] | None, agent_filters: list[str] | None) -> None:
  repo = _get_jobs_repo(settings)
  target_agents = {str(item) for item in (agent_filters or list(_LESSON_RESUMABLE_AGENTS))}
  normalized_sections = {int(item) for item in section_filters} if section_filters else None
  lesson_id = str(job.lesson_id or "")
  if lesson_id == "":
    return
  session_factory = get_session_factory()
  if session_factory is None:
    return
  storage_client = build_storage_client(settings)
  async with session_factory() as session:
    section_rows = (await session.execute(select(Section).where(Section.lesson_id == lesson_id).order_by(Section.order_index.asc()))).scalars().all()
    existing_indexes = {int(section_row.order_index) for section_row in section_rows}
    if "planner" in target_agents:
      await repo.upsert_checkpoint(job_id=job.job_id, stage="planner", section_index=None, state="done" if section_rows else "pending", artifact_refs_json={"lesson_id": lesson_id})
    for section_row in section_rows:
      section_index = int(section_row.order_index)
      if normalized_sections is not None and section_index not in normalized_sections:
        continue
      section_ready = bool(section_row.content and section_row.status == "completed")
      if "section_builder" in target_agents:
        await repo.upsert_checkpoint(job_id=job.job_id, stage="section_builder", section_index=section_index, state="done" if section_ready else "pending", artifact_refs_json={"section_id": int(section_row.section_id)})
      if "illustration" in target_agents:
        illustration_ready = False
        illustration_id = int(section_row.illustration_id) if section_row.illustration_id else None
        if illustration_id is not None:
          illustration_row = await session.get(Illustration, illustration_id)
          if illustration_row is not None and illustration_row.status == "completed" and str(illustration_row.storage_object_name or "").strip():
            try:
              illustration_ready = await storage_client.exists(str(illustration_row.storage_object_name))
            except Exception:  # noqa: BLE001
              illustration_ready = False
        await repo.upsert_checkpoint(
          job_id=job.job_id, stage="illustration", section_index=section_index, state="done" if illustration_ready else "pending", artifact_refs_json={"section_id": int(section_row.section_id), "illustration_id": illustration_id}
        )
      if "tutor" in target_agents:
        tutor_id = int(section_row.tutor_id) if section_row.tutor_id else None
        tutor_ready = False
        if tutor_id is not None:
          tutor_row = await session.get(Tutor, tutor_id)
          tutor_ready = bool(tutor_row is not None and tutor_row.status == "completed" and tutor_row.audio_data)
        await repo.upsert_checkpoint(job_id=job.job_id, stage="tutor", section_index=section_index, state="done" if tutor_ready else "pending", artifact_refs_json={"section_number": section_index, "tutor_id": tutor_id})
      if "fenster_builder" in target_agents:
        widget_rows = (
          await session.execute(
            select(SubsectionWidget.public_id, SubsectionWidget.widget_id, SubsectionWidget.status)
            .join(Subsection, Subsection.id == SubsectionWidget.subsection_id)
            .where(Subsection.section_id == int(section_row.section_id), SubsectionWidget.widget_type == "fenster")
          )
        ).all()
        expected_widget_ids = [str(row.public_id) for row in widget_rows]
        completed_widgets = [str(row.public_id) for row in widget_rows if str(row.status or "") == "completed" and str(row.widget_id or "").strip()]
        if not expected_widget_ids:
          state = "skipped"
        else:
          state = "done" if len(completed_widgets) == len(expected_widget_ids) else "pending"
        await repo.upsert_checkpoint(job_id=job.job_id, stage="fenster_builder", section_index=section_index, state=state, artifact_refs_json={"section_id": int(section_row.section_id), "widget_public_ids": expected_widget_ids})
    if normalized_sections:
      missing_indexes = sorted(normalized_sections - existing_indexes)
      for missing_index in missing_indexes:
        for stage in ("section_builder", "illustration", "tutor", "fenster_builder"):
          if stage not in target_agents:
            continue
          await repo.upsert_checkpoint(job_id=job.job_id, stage=stage, section_index=int(missing_index), state="pending", artifact_refs_json={"lesson_id": lesson_id, "section_index": int(missing_index)})


async def cancel_job(job_id: str, settings: Settings, user_id: str | None = None) -> JobStatusResponse:
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  if user_id and record.user_id != user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  if record.status in ("done", "error", "canceled", "superseded"):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is already finalized and cannot be canceled.")
  updated = await repo.update_job(job_id, status="canceled", completed_at=time.strftime(_DATE_FORMAT, time.gmtime()), logs=["Job cancellation requested by client."])
  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  child_jobs = await _resolve_child_jobs(updated, settings)
  return _job_status_from_record(updated, child_jobs=child_jobs, requested_job_id=job_id, resolved_job_id=updated.job_id)


async def get_job_status(job_id: str, settings: Settings, user_id: str | None = None) -> JobStatusResponse:
  if not user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  repo = _get_jobs_repo(settings)
  requested = await repo.get_job(job_id)
  if requested is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  if requested.user_id != user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  resolved = await _resolve_latest_record(requested, settings)
  child_jobs = await _resolve_child_jobs(resolved, settings)
  return _job_status_from_record(
    resolved,
    child_jobs=child_jobs,
    requested_job_id=requested.job_id,
    resolved_job_id=resolved.job_id,
    superseded_job_id=requested.job_id if requested.job_id != resolved.job_id else None,
    follow_from_job_id=resolved.job_id if requested.job_id != resolved.job_id else None,
  )


async def process_job_sync(job_id: str, settings: Settings) -> JobRecord | None:
  repo = _get_jobs_repo(settings)
  try:
    from app.jobs.worker import JobProcessor

    record = await repo.get_job(job_id)
    if record is None:
      return None
    processor = JobProcessor(jobs_repo=repo, settings=settings)
    return await processor.process_job(record)
  except Exception as exc:  # noqa: BLE001
    logger.error("Synchronous job processing failed for job %s: %s", job_id, exc, exc_info=True)
    try:
      await repo.update_job(job_id, status="error", logs=[f"System error during job initialization: {exc}"], error_json={"message": str(exc)})
    except Exception as update_exc:  # noqa: BLE001
      logger.error("Failed to update job status after processing error: %s", update_exc)
    return None


def trigger_job_processing(background_tasks: BackgroundTasks, job_id: str, settings: Settings, *, auto_process: bool = True) -> None:
  if not auto_process:
    return
  enqueuer = get_task_enqueuer(settings)

  async def _dispatch() -> None:
    try:
      await enqueuer.enqueue(job_id, {})
    except Exception as exc:  # noqa: BLE001
      logger.error("Failed to enqueue job %s: %s", job_id, exc, exc_info=True)
      repo = _get_jobs_repo(settings)
      record = await repo.get_job(job_id)
      if record is not None and record.status == "queued":
        await repo.update_job(job_id, status="error", logs=["Enqueue failed: TASK_ENQUEUE_FAILED"], error_json={"message": str(exc)})

  background_tasks.add_task(_dispatch)
