import logging
import time
import uuid
from typing import Any

from app.api.models import CurrentSectionStatus, GenerateLessonRequest, JobCreateResponse, JobRetryRequest, JobStatusResponse, ValidationResponse, WritingCheckRequest
from app.config import Settings
from app.jobs.models import JobRecord
from app.services.audit import log_llm_interaction
from app.services.model_routing import _get_orchestrator, _resolve_model_selection
from app.services.request_validation import _validate_generate_request
from app.services.tasks.factory import get_task_enqueuer
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id
from fastapi import BackgroundTasks, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_JOB_NOT_FOUND_MSG = "Job not found."
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


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
  return {key: value for key, value in payload.items() if not key.startswith("_")}


def _job_status_from_record(record: JobRecord, settings: Settings) -> JobStatusResponse:
  """Convert a persisted job record into an API response payload."""

  # Parse the stored payload into the correct request model for the job type.
  try:
    request = _parse_job_request(record.request)

  except ValidationError as exc:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stored job request failed validation.") from exc

  validation = None

  if record.validation is not None:
    validation = ValidationResponse.model_validate(record.validation)

  expected_sections = record.expected_sections

  # Backfill expected section counts for legacy job records.
  if expected_sections is None and isinstance(request, GenerateLessonRequest):
    expected_sections = _expected_sections_from_request(request, settings)

  if expected_sections is None and isinstance(request, WritingCheckRequest):
    expected_sections = 0

  current_section = None

  if record.current_section_index is not None and record.current_section_status is not None:
    current_section = CurrentSectionStatus(index=record.current_section_index, title=record.current_section_title, status=record.current_section_status, retry_count=record.current_section_retry_count)

  return JobStatusResponse(
    job_id=record.job_id,
    status=record.status,
    phase=record.phase,
    subphase=record.subphase,
    expected_sections=expected_sections,
    completed_sections=record.completed_sections,
    completed_section_indexes=record.completed_section_indexes,
    current_section=current_section,
    retry_count=record.retry_count,
    max_retries=record.max_retries,
    retry_sections=record.retry_sections,
    retry_agents=record.retry_agents,
    total_steps=record.total_steps,
    completed_steps=record.completed_steps,
    progress=record.progress,
    logs=record.logs or [],
    result=record.result_json,
    validation=validation,
    cost=record.cost,
    created_at=record.created_at,
    updated_at=record.updated_at,
    completed_at=record.completed_at,
  )


async def create_job(request: GenerateLessonRequest, settings: Settings, background_tasks: BackgroundTasks, db_session: AsyncSession, *, user_id: str | None = None) -> JobCreateResponse:
  """Create a background lesson generation job."""
  _validate_generate_request(request, settings)

  selection = _resolve_model_selection(settings, models=request.models)
  model_name = f"job:{selection[1]},{selection[3]},{selection[5]}"

  if user_id:
    try:
      u_uuid = uuid.UUID(str(user_id))
      await log_llm_interaction(user_id=u_uuid, model_name=model_name, prompt_summary=request.topic, status="job_queued", session=db_session)
    except ValueError:
      logger.warning("Invalid user_id for logging: %s", user_id)

  repo = _get_jobs_repo(settings)
  # Precompute section count so the client can render placeholders immediately.
  expected_sections = _expected_sections_from_request(request, settings)

  if request.idempotency_key:
    existing = await repo.find_by_idempotency_key(request.idempotency_key)

    if existing:
      response_expected = existing.expected_sections or expected_sections
      return JobCreateResponse(job_id=existing.job_id, expected_sections=response_expected)

  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  request_payload = request.model_dump(mode="python", by_alias=True)
  # Persist minimal metadata for worker-side notifications without storing email addresses.
  if user_id:
    request_payload["_meta"] = {"user_id": user_id}

  record = JobRecord(
    job_id=job_id,
    request=request_payload,
    status="queued",
    phase="queued",
    subphase=None,
    expected_sections=expected_sections,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=settings.job_max_retries,
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


async def retry_job(job_id: str, payload: JobRetryRequest, settings: Settings, background_tasks: BackgroundTasks) -> JobStatusResponse:
  """Retry a failed job with optional section/agent targeting."""
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)

  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)

  # Only finalized failures should be eligible for retry.
  if record.status not in ("error", "canceled"):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed or canceled jobs can be retried.")

  # Enforce the retry limit to avoid unbounded reprocessing.
  retry_count = record.retry_count or 0
  max_retries = record.max_retries if record.max_retries is not None else settings.job_max_retries

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
  return _job_status_from_record(updated, settings)


async def cancel_job(job_id: str, settings: Settings) -> JobStatusResponse:
  """Request cancellation of a running background job."""
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  if record.status in ("done", "error", "canceled"):
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job is already finalized and cannot be canceled.")
  updated = await repo.update_job(job_id, status="canceled", phase="canceled", subphase=None, progress=100.0, logs=record.logs + ["Job cancellation requested by client."], completed_at=time.strftime(_DATE_FORMAT, time.gmtime()))
  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  return _job_status_from_record(updated, settings)


async def get_job_status(job_id: str, settings: Settings) -> JobStatusResponse:
  """Fetch the status and result of a background job."""
  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  return _job_status_from_record(record, settings)

  return _job_status_from_record(record, settings)


async def process_job_sync(job_id: str, settings: Settings) -> None:
  """Run a queued job immediately (synchronously)."""
  from app.jobs.worker import JobProcessor

  repo = _get_jobs_repo(settings)
  record = await repo.get_job(job_id)

  if record is None:
    return

  processor = JobProcessor(jobs_repo=repo, orchestrator=_get_orchestrator(settings), settings=settings)
  await processor.process_job(record)


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

  # Schedule the dispatch coroutine on the background tasks
  # We use background_tasks to ensure we don't block the API response
  # while waiting for the network call to Cloud Tasks or local dispatcher.
  background_tasks.add_task(_dispatch)
