import logging
import time
import uuid
from typing import Any

from app.api.models import ChildJobStatus, JobCreateRequest, JobCreateResponse, JobRetryRequest, JobStatusResponse
from app.config import Settings
from app.jobs.models import JobKind, JobRecord
from app.schema.quotas import QuotaPeriod
from app.services.quota_buckets import get_quota_snapshot
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.tasks.factory import get_task_enqueuer
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id
from fastapi import BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_JOB_NOT_FOUND_MSG = "Job not found."
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_COMPATIBLE_TARGETS: dict[JobKind, set[str]] = {
  "lesson": {"planner", "section_builder", "coach", "fenster_builder", "illustration"},
  "research": {"research"},
  "youtube": {"youtube"},
  "maintenance": {"maintenance"},
  "writing": {"writing"},
  "system": {"maintenance"},
}
_TARGET_METRICS: dict[str, tuple[str, str, QuotaPeriod]] = {
  "planner": ("limits.lessons_per_week", "lesson.generate", QuotaPeriod.WEEK),
  "section_builder": ("limits.sections_per_month", "section.generate", QuotaPeriod.MONTH),
  "coach": ("limits.coach_sections_per_month", "coach.generate", QuotaPeriod.MONTH),
  "fenster_builder": ("limits.fenster_widgets_per_month", "fenster.widget.generate", QuotaPeriod.MONTH),
  "illustration": ("limits.image_generations_per_month", "image.generate", QuotaPeriod.MONTH),
  "writing": ("limits.writing_checks_per_month", "writing.check", QuotaPeriod.MONTH),
  "ocr": ("limits.ocr_files_per_month", "ocr.extract", QuotaPeriod.MONTH),
}


def _compute_job_ttl(settings: Settings) -> int | None:
  """Compute optional TTL expiry for a queued job."""
  if settings.jobs_ttl_seconds is None:
    return None
  return int(time.time()) + settings.jobs_ttl_seconds


def _expected_sections_from_payload(payload: dict[str, Any], target_agent: str) -> int:
  """Compute expected lesson sections from a planner payload."""
  if target_agent != "planner":
    return 0
  depth = str(payload.get("depth") or "highlights").strip().lower()
  mapping = {"highlights": 2, "detailed": 6, "training": 10}
  return int(mapping.get(depth, 2))


def _job_status_from_record(record: JobRecord, *, child_jobs: list[ChildJobStatus] | None = None) -> JobStatusResponse:
  """Convert a persisted job record into the minimal status response."""
  return JobStatusResponse(job_id=record.job_id, status=record.status, child_jobs=child_jobs, lesson_id=record.lesson_id)


async def _resolve_child_jobs(record: JobRecord, settings: Settings) -> list[ChildJobStatus] | None:
  """Resolve direct non-done child jobs for a parent record."""
  repo = _get_jobs_repo(settings)
  children = await repo.list_child_jobs(parent_job_id=record.job_id, include_done=False)
  if not children:
    return None
  statuses: list[ChildJobStatus] = []
  for child in children:
    statuses.append(ChildJobStatus(job_id=child.job_id, status=child.status))
  return statuses


async def _ensure_quota_available(db_session: AsyncSession, *, settings: Settings, user_id: str | None, target_agent: str) -> None:
  """Check whether quota exists and has remaining capacity for this target agent."""
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
  """Create a background job from a generic job request payload."""
  if user_id is None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  compatible_targets = _COMPATIBLE_TARGETS.get(request.job_kind, set())
  if request.target_agent not in compatible_targets:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="target_agent is not valid for job_kind.")
  await _ensure_quota_available(db_session, settings=settings, user_id=user_id, target_agent=request.target_agent)
  repo = _get_jobs_repo(settings)
  existing = await repo.find_by_user_kind_idempotency_key(user_id=user_id, job_kind=request.job_kind, idempotency_key=request.idempotency_key)
  if existing is not None:
    return JobCreateResponse(job_id=existing.job_id, expected_sections=existing.expected_sections or 0)
  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  expected_sections = _expected_sections_from_payload(request.payload, request.target_agent)
  record = JobRecord(
    job_id=job_id,
    user_id=user_id,
    job_kind=request.job_kind,
    request=request.payload,
    status="queued",
    parent_job_id=request.parent_job_id,
    lesson_id=request.lesson_id,
    section_id=request.section_id,
    target_agent=request.target_agent,
    phase="queued",
    subphase=None,
    expected_sections=expected_sections,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=0,
    retry_sections=None,
    retry_agents=None,
    progress=0.0,
    logs=[],
    result_json=None,
    validation=None,
    cost=None,
    created_at=timestamp,
    updated_at=timestamp,
    completed_at=None,
    ttl=_compute_job_ttl(settings),
    idempotency_key=request.idempotency_key,
  )
  await repo.create_job(record)
  trigger_job_processing(background_tasks, job_id, settings)
  return JobCreateResponse(job_id=job_id, expected_sections=expected_sections)


async def retry_job(job_id: str, payload: JobRetryRequest, settings: Settings, background_tasks: BackgroundTasks, user_id: str | None = None) -> JobStatusResponse:
  """Manually retry a failed/canceled job without automatic retry limits."""
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  if user_id and record.user_id != user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  if record.status not in ("error", "canceled"):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed or canceled jobs can be retried.")
  # Preserve client payload validation semantics even though manual retries are node-local now.
  _ = payload
  logs = list(record.logs or []) + ["Manual retry queued."]
  updated = await repo.update_job(job_id, status="queued", phase="queued", subphase="manual_retry", progress=0.0, logs=logs, completed_at=None)
  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
  trigger_job_processing(background_tasks, updated.job_id, settings)
  child_jobs = await _resolve_child_jobs(updated, settings)
  return _job_status_from_record(updated, child_jobs=child_jobs)


async def cancel_job(job_id: str, settings: Settings, user_id: str | None = None) -> JobStatusResponse:
  """Request cancellation of a running background job."""
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  if user_id and record.user_id != user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  if record.status in ("done", "error", "canceled"):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is already finalized and cannot be canceled.")
  updated = await repo.update_job(job_id, status="canceled", phase="canceled", subphase=None, progress=100.0, logs=list(record.logs or []) + ["Job cancellation requested by client."], completed_at=time.strftime(_DATE_FORMAT, time.gmtime()))
  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  child_jobs = await _resolve_child_jobs(updated, settings)
  return _job_status_from_record(updated, child_jobs=child_jobs)


async def get_job_status(job_id: str, settings: Settings, user_id: str | None = None) -> JobStatusResponse:
  """Fetch minimal status payload for a background job."""
  if not user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  if record.user_id != user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
  child_jobs = await _resolve_child_jobs(record, settings)
  return _job_status_from_record(record, child_jobs=child_jobs)


async def process_job_sync(job_id: str, settings: Settings) -> JobRecord | None:
  """Run a queued job immediately (synchronously)."""
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
      await repo.update_job(job_id, status="error", phase="failed", progress=100.0, logs=[f"System error during job initialization: {exc}"])
    except Exception as update_exc:  # noqa: BLE001
      logger.error("Failed to update job status after processing error: %s", update_exc)
    return None


def trigger_job_processing(background_tasks: BackgroundTasks, job_id: str, settings: Settings) -> None:
  """Schedule background processing via the configured task enqueuer."""
  if not settings.jobs_auto_process:
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
        await repo.update_job(job_id, status="error", phase="failed", progress=100.0, logs=list(record.logs or []) + ["Enqueue failed: TASK_ENQUEUE_FAILED"])

  background_tasks.add_task(_dispatch)
