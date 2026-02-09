import logging
import time
import uuid
from typing import Any

from app.api.models import ChildJobStatus, GenerateLessonRequest, JobCreateResponse, JobRetryRequest, JobStatusResponse, WritingCheckRequest
from app.config import Settings
from app.jobs.models import JobRecord
from app.schema.quotas import QuotaPeriod
from app.services.audit import log_llm_interaction
from app.services.model_routing import _get_orchestrator, resolve_agent_defaults
from app.services.quota_buckets import get_quota_snapshot
from app.services.request_validation import _validate_generate_request
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.tasks.factory import get_task_enqueuer
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id
from fastapi import BackgroundTasks, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_JOB_NOT_FOUND_MSG = "Job not found."
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_KNOWN_JOB_STATUSES = {"queued", "running", "done", "error", "canceled"}


def _resolve_target_agent(request: GenerateLessonRequest | WritingCheckRequest, target_agent: str | None) -> str | None:
  """Resolve a stable target agent for quota gating and persistence."""
  # Preserve explicit target routing when callers provide it.
  if target_agent:
    return target_agent

  # Default lesson requests to the lesson pipeline when target routing is omitted.
  if isinstance(request, GenerateLessonRequest):
    return "lesson"

  # Default writing checks to the writing worker when target routing is omitted.
  if isinstance(request, WritingCheckRequest):
    return "writing"

  return target_agent


def _compute_job_ttl(settings: Settings) -> int | None:
  if settings.jobs_ttl_seconds is None:
    return None
  return int(time.time()) + settings.jobs_ttl_seconds


def _expected_sections_from_request(request: GenerateLessonRequest, settings: Settings) -> int:
  """Compute the expected section count for a lesson job."""
  # Reuse the call plan depth so expected section counts match worker planning.
  from app.jobs.progress import build_call_plan

  plan = build_call_plan(request.model_dump(mode="python", by_alias=True))
  return plan.depth


def _parse_job_request(payload: dict[str, Any]) -> GenerateLessonRequest | WritingCheckRequest:
  """Resolve the stored job request to the correct request model."""

  # Writing checks carry a distinct payload shape (text + criteria).
  payload = _strip_internal_fields(payload)

  if "text" in payload and "criteria" in payload:
    return WritingCheckRequest.model_validate(payload)

  # Drop deprecated fields so legacy records can still be parsed.
  if "mode" in payload:
    payload = {key: value for key, value in payload.items() if key != "mode"}

  return GenerateLessonRequest.model_validate(payload)


def _strip_internal_fields(payload: dict[str, Any]) -> dict[str, Any]:
  """Remove internal-only metadata keys from a stored job request payload."""
  # Job requests are persisted as JSON and may include internal fields (e.g. _meta).
  cleaned = {key: value for key, value in payload.items() if not key.startswith("_")}

  # Drop deprecated model overrides to keep request parsing stable.
  cleaned.pop("models", None)
  cleaned.pop("checker_model", None)

  return cleaned


def _job_status_from_record(record: JobRecord, settings: Settings, *, child_jobs: list[ChildJobStatus] | None = None) -> JobStatusResponse:
  """Convert a persisted job record into an API response payload."""

  lesson_id = None
  # Extract lesson_id from result_json if available
  if record.result_json:
    lesson_id = record.result_json.get("lesson_id")

  return JobStatusResponse(job_id=record.job_id, status=record.status, child_jobs=child_jobs, lesson_id=lesson_id)


def _normalize_job_status(raw_status: str | None) -> str:
  """Normalize unknown job statuses into a safe default."""
  # Clamp unknown status values to "queued" so responses remain predictable.
  if raw_status and raw_status in _KNOWN_JOB_STATUSES:
    return raw_status
  return "queued"


async def _resolve_child_jobs(record: JobRecord, settings: Settings) -> list[ChildJobStatus] | None:
  """Resolve child job status payloads from job artifacts."""
  # Extract child job references from persisted artifacts.
  artifacts = record.artifacts or {}
  raw_children = artifacts.get("child_jobs")
  if not isinstance(raw_children, list) or not raw_children:
    return None
  # Resolve job records so the UI sees current status values.
  repo = _get_jobs_repo(settings)
  child_statuses: list[ChildJobStatus] = []
  for child in raw_children:
    if not isinstance(child, dict):
      continue
    # Require a valid child job id before lookup.
    child_id = child.get("job_id")
    if not isinstance(child_id, str) or child_id.strip() == "":
      continue
    child_record = await repo.get_job(child_id)
    if child_record is None:
      status = _normalize_job_status(str(child.get("status") or "queued"))
      child_statuses.append(ChildJobStatus(job_id=child_id, status=status))
      continue
    # Prefer live job records when available.
    child_statuses.append(ChildJobStatus(job_id=child_record.job_id, status=child_record.status))
  return child_statuses or None


async def create_job(request: GenerateLessonRequest | WritingCheckRequest, settings: Settings, background_tasks: BackgroundTasks, db_session: AsyncSession, *, user_id: str | None = None, target_agent: str | None = None) -> JobCreateResponse:
  """Create a background lesson generation job."""
  if isinstance(request, GenerateLessonRequest):
    _validate_generate_request(request, settings)

  repo = _get_jobs_repo(settings)

  # Idempotency Check: Return existing job if the key is already present.
  if request.idempotency_key:
    existing = await repo.find_by_idempotency_key(request.idempotency_key)
    if existing:
      # Verify ownership if user_id is provided to prevent key hijacking across users.
      if user_id is None or existing.user_id == user_id:
        logger.info("Retrieved existing job %s for idempotency key %s", existing.job_id, request.idempotency_key)
        return JobCreateResponse(job_id=existing.job_id, expected_sections=existing.expected_sections or 0)

  repo = _get_jobs_repo(settings)
  # Precompute section count so the client can render placeholders immediately.
  expected_sections = _expected_sections_from_request(request, settings) if isinstance(request, GenerateLessonRequest) else 0
  # Resolve the effective target once so quota checks and persistence remain aligned.
  effective_target_agent = _resolve_target_agent(request, target_agent)
  # Generate identifiers early so quota logs can reference the resulting job deterministically.
  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  # Enforce lesson and section quotas for lesson jobs, failing fast before persisting the job.
  lesson_user = None
  lesson_tier_id: int | None = None
  if isinstance(request, GenerateLessonRequest) and user_id and effective_target_agent == "lesson":
    try:
      parsed_user_id = uuid.UUID(str(user_id))
    except ValueError as exc:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.") from exc
    lesson_user = await get_user_by_id(db_session, parsed_user_id)
    if lesson_user is None:
      raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    lesson_tier_id, _tier_name = await get_user_subscription_tier(db_session, lesson_user.id)
    runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=lesson_user.org_id, subscription_tier_id=lesson_tier_id, user_id=None)
    lessons_per_week = int(runtime_config.get("limits.lessons_per_week") or 0)
    sections_per_month = int(runtime_config.get("limits.sections_per_month") or 0)
    if lessons_per_week <= 0:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "lesson.generate"})
    if sections_per_month <= 0:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "section.generate"})
    lesson_snapshot = await get_quota_snapshot(db_session, user_id=lesson_user.id, metric_key="lesson.generate", period=QuotaPeriod.WEEK, limit=lessons_per_week)
    if lesson_snapshot.remaining <= 0:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "lesson.generate"})
    section_snapshot = await get_quota_snapshot(db_session, user_id=lesson_user.id, metric_key="section.generate", period=QuotaPeriod.MONTH, limit=sections_per_month)
    if section_snapshot.remaining <= 0:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "section.generate"})
    expected_sections = min(int(expected_sections), int(section_snapshot.remaining))
    if expected_sections <= 0:
      raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "section.generate"})
    # Defer lesson quota reservation to the planner agent so reservations are scoped to agent execution.

  elif effective_target_agent == "coach":
    if user_id:
      try:
        parsed_user_id = uuid.UUID(str(user_id))
        user = await get_user_by_id(db_session, parsed_user_id)
        if user:
          tier_id, _ = await get_user_subscription_tier(db_session, user.id)
          runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
          limit = int(runtime_config.get("limits.coach_sections_per_month") or 0)
          if limit <= 0:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "coach.generate"})
          snapshot = await get_quota_snapshot(db_session, user_id=user.id, metric_key="coach.generate", period=QuotaPeriod.MONTH, limit=limit)
          if snapshot.remaining <= 0:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "coach.generate"})
      except ValueError:
        pass

  elif effective_target_agent == "fenster_builder":
    if user_id:
      try:
        parsed_user_id = uuid.UUID(str(user_id))
        user = await get_user_by_id(db_session, parsed_user_id)
        if user:
          tier_id, _ = await get_user_subscription_tier(db_session, user.id)
          runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
          limit = int(runtime_config.get("limits.fenster_widgets_per_month") or 0)
          if limit <= 0:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "fenster.widget.generate"})
          snapshot = await get_quota_snapshot(db_session, user_id=user.id, metric_key="fenster.widget.generate", period=QuotaPeriod.MONTH, limit=limit)
          if snapshot.remaining <= 0:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "fenster.widget.generate"})
      except ValueError:
        pass

  elif effective_target_agent == "writing":
    if user_id:
      try:
        parsed_user_id = uuid.UUID(str(user_id))
        user = await get_user_by_id(db_session, parsed_user_id)
        if user:
          tier_id, _ = await get_user_subscription_tier(db_session, user.id)
          runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
          limit = int(runtime_config.get("limits.writing_checks_per_month") or 0)
          if limit <= 0:
            # Writing check route also checks this, but we double-check here for safety
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "writing.check"})
          snapshot = await get_quota_snapshot(db_session, user_id=user.id, metric_key="writing.check", period=QuotaPeriod.MONTH, limit=limit)
          if snapshot.remaining <= 0:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "writing.check"})
      except ValueError:
        pass

  elif effective_target_agent == "ocr":
    if user_id:
      try:
        parsed_user_id = uuid.UUID(str(user_id))
        user = await get_user_by_id(db_session, parsed_user_id)
        if user:
          tier_id, _ = await get_user_subscription_tier(db_session, user.id)
          runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
          limit = int(runtime_config.get("limits.ocr_files_per_month") or 0)
          if limit <= 0:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "ocr.extract"})
          snapshot = await get_quota_snapshot(db_session, user_id=user.id, metric_key="ocr.extract", period=QuotaPeriod.MONTH, limit=limit)
          if snapshot.remaining <= 0:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "ocr.extract"})
      except ValueError:
        pass

  # Resolve model defaults for logging after tier-based config is known.
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=None, subscription_tier_id=None, user_id=None)

  if lesson_user is not None and lesson_tier_id is not None:
    runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=lesson_user.org_id, subscription_tier_id=lesson_tier_id, user_id=None)

  selection = resolve_agent_defaults(settings, runtime_config)
  model_name = f"job:{selection[1]},{selection[3]},{selection[5]}"

  if user_id:
    try:
      u_uuid = uuid.UUID(str(user_id))
      prompt_summary = request.topic if isinstance(request, GenerateLessonRequest) else "writing-check"
      await log_llm_interaction(user_id=u_uuid, model_name=model_name, prompt_summary=prompt_summary, status="job_queued", session=db_session)
    except ValueError:
      logger.warning("Invalid user_id for logging: %s", user_id)

  request_payload = request.model_dump(mode="python", by_alias=True)
  # Persist minimal metadata for worker-side notifications without storing email addresses.
  if user_id:
    request_payload["_meta"] = {"user_id": user_id, "quota_cap_sections": int(expected_sections)}

  record = JobRecord(
    job_id=job_id,
    user_id=user_id,
    request=request_payload,
    status="queued",
    target_agent=effective_target_agent,
    phase="queued",
    subphase=None,
    expected_sections=expected_sections,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    # Enforce a strict retry cap for lesson jobs so quota accounting cannot drift.
    max_retries=1 if isinstance(request, GenerateLessonRequest) else settings.job_max_retries,
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

  # Kick off processing
  trigger_job_processing(background_tasks, job_id, settings)

  return JobCreateResponse(job_id=job_id, expected_sections=expected_sections)


async def retry_job(job_id: str, payload: JobRetryRequest, settings: Settings, background_tasks: BackgroundTasks, user_id: str | None = None) -> JobStatusResponse:
  """Retry a failed job with optional section/agent targeting."""
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)

  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)

  if user_id and record.user_id != user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

  # Only finalized failures should be eligible for retry.
  if record.status not in ("error", "canceled"):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed or canceled jobs can be retried.")

  # Enforce the retry limit to avoid unbounded reprocessing.
  retry_count = record.retry_count or 0
  max_retries = record.max_retries if record.max_retries is not None else settings.job_max_retries
  # Clamp lesson jobs to a maximum of one retry to keep quota accounting strict.
  if record.target_agent == "lesson":
    max_retries = min(int(max_retries), 1)

  if retry_count >= max_retries:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Retry limit reached for this job.")

  # Resolve expected sections for validation against retry targets.
  try:
    parsed_request = _parse_job_request(record.request)

  except ValidationError as exc:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stored job request failed validation.") from exc

  if isinstance(parsed_request, WritingCheckRequest):
    if payload.sections or payload.agents:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Writing check retries do not support section or agent targeting.")
    expected_sections = 0

  else:
    expected_sections = record.expected_sections or _expected_sections_from_request(parsed_request, settings)

  # Normalize retry sections to a unique, ordered list.
  retry_sections = None

  if payload.sections:
    # Ensure retry section indexes are within expected bounds.
    invalid = [index for index in payload.sections if index >= expected_sections]

    if invalid:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Retry section indexes exceed expected section count.")
    retry_sections = sorted(set(payload.sections))

  # Preserve agent order while deduplicating retry targets.
  retry_agents: list[str] | None = None
  if payload.agents:
    retry_agents = list(dict.fromkeys(payload.agents))

  logs = record.logs + [f"Retry attempt {retry_count + 1} queued."]
  # Requeue the job with retry metadata so the worker can resume.
  updated = await repo.update_job(
    job_id,
    status="queued",
    phase="queued",
    subphase="retry",
    progress=0.0,
    logs=logs,
    retry_count=retry_count + 1,
    max_retries=max_retries,
    retry_sections=retry_sections,
    retry_agents=retry_agents,
    current_section_index=None,
    current_section_status=None,
    current_section_retry_count=None,
    current_section_title=None,
    completed_at=None,
  )

  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

  trigger_job_processing(background_tasks, updated.job_id, settings)
  child_jobs = await _resolve_child_jobs(updated, settings)
  return _job_status_from_record(updated, settings, child_jobs=child_jobs)


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
  updated = await repo.update_job(job_id, status="canceled", phase="canceled", subphase=None, progress=100.0, logs=record.logs + ["Job cancellation requested by client."], completed_at=time.strftime(_DATE_FORMAT, time.gmtime()))
  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  child_jobs = await _resolve_child_jobs(updated, settings)
  return _job_status_from_record(updated, settings, child_jobs=child_jobs)


async def get_job_status(job_id: str, settings: Settings, user_id: str | None = None) -> JobStatusResponse:
  """Fetch the status and result of a background job."""
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)

  if user_id and record.user_id != user_id:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

  child_jobs = await _resolve_child_jobs(record, settings)
  return _job_status_from_record(record, settings, child_jobs=child_jobs)


async def process_job_sync(job_id: str, settings: Settings) -> JobRecord | None:
  """Run a queued job immediately (synchronously)."""
  repo = _get_jobs_repo(settings)
  try:
    from app.jobs.worker import JobProcessor

    record = await repo.get_job(job_id)

    if record is None:
      return

    processor = JobProcessor(jobs_repo=repo, orchestrator=_get_orchestrator(settings), settings=settings)
    return await processor.process_job(record)
  except Exception as exc:
    logger.error("Synchronous job processing failed for job %s: %s", job_id, exc, exc_info=True)
    try:
      await repo.update_job(job_id, status="error", phase="failed", progress=100.0, logs=[f"System error during job initialization: {exc}"])
    except Exception as update_exc:
      logger.error("Failed to update job status after processing error: %s", update_exc)
    return None


def trigger_job_processing(background_tasks: BackgroundTasks, job_id: str, settings: Settings) -> None:
  """Schedule background processing via the configured task enqueuer."""

  if not settings.jobs_auto_process:
    return

  # Use the configured task enqueuer (GCP or Local) to dispatch the job.
  enqueuer = get_task_enqueuer(settings)

  async def _dispatch() -> None:
    try:
      await enqueuer.enqueue(job_id, {})
    except Exception as exc:  # noqa: BLE001
      logger.error("Failed to enqueue job %s: %s", job_id, exc, exc_info=True)
      # Mark the job as failed on enqueue errors so queued jobs do not stay pending forever.
      repo = _get_jobs_repo(settings)
      record = await repo.get_job(job_id)
      if record is not None and record.status == "queued":
        await repo.update_job(job_id, status="error", phase="failed", progress=100.0, logs=record.logs + ["Enqueue failed: TASK_ENQUEUE_FAILED"])

  # Schedule the dispatch coroutine on the background tasks
  # We use background_tasks to ensure we don't block the API response
  # while waiting for the network call to Cloud Tasks or local dispatcher.
  background_tasks.add_task(_dispatch)
