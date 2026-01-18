"""Shared job processing logic."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import BackgroundTasks, HTTPException, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.models import (
  CurrentSectionStatus,
  GenerateLessonRequest,
  JobCreateResponse,
  JobStatusResponse,
  ValidationResponse,
  WritingCheckRequest,
)
from app.config import Settings
from app.jobs.models import JobRecord
from app.services.orchestrator import _get_orchestrator
from app.services.validation import _validate_generate_request
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id

logger = logging.getLogger("app.services.jobs")

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_JOB_NOT_FOUND_MSG = "Job not found."


def _compute_job_ttl(settings: Settings) -> int | None:
  if settings.jobs_ttl_seconds is None:
    return None
  return int(time.time()) + settings.jobs_ttl_seconds


def _expected_sections_from_request(request: GenerateLessonRequest, settings: Settings) -> int:
  """Compute the expected section count for a lesson job."""
  # Reuse the call plan depth so expected section counts match worker planning.
  from app.jobs.progress import build_call_plan

  plan = build_call_plan(
    request.model_dump(mode="python", by_alias=True), merge_gatherer_structurer=settings.merge_gatherer_structurer
  )
  return plan.depth


def _parse_job_request(payload: dict[str, Any]) -> GenerateLessonRequest | WritingCheckRequest:
  """Resolve the stored job request to the correct request model."""

  # Writing checks carry a distinct payload shape (text + criteria).

  if "text" in payload and "criteria" in payload:
    return WritingCheckRequest.model_validate(payload)

  # Drop deprecated fields so legacy records can still be parsed.
  if "mode" in payload:
    payload = {key: value for key, value in payload.items() if key != "mode"}

  return GenerateLessonRequest.model_validate(payload)


def _job_status_from_record(record: JobRecord, settings: Settings) -> JobStatusResponse:
  """Convert a persisted job record into an API response payload."""

  # Parse the stored payload into the correct request model for the job type.
  try:
    request = _parse_job_request(record.request)
  except ValidationError as exc:
    raise HTTPException(
      status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Stored job request failed validation."
    ) from exc

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
    current_section = CurrentSectionStatus(
      index=record.current_section_index,
      title=record.current_section_title,
      status=record.current_section_status,
      retry_count=record.current_section_retry_count,
    )

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


async def _create_job_record(request: GenerateLessonRequest, settings: Settings) -> JobCreateResponse:
  _validate_generate_request(request, settings)
  repo = _get_jobs_repo(settings)
  # Precompute section count so the client can render placeholders immediately.
  expected_sections = _expected_sections_from_request(request, settings)

  if request.idempotency_key:
    existing = await run_in_threadpool(repo.find_by_idempotency_key, request.idempotency_key)

    if existing:
      response_expected = existing.expected_sections or expected_sections
      return JobCreateResponse(job_id=existing.job_id, expected_sections=response_expected)

  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  request_payload = request.model_dump(mode="python", by_alias=True)
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
  await run_in_threadpool(repo.create_job, record)
  return JobCreateResponse(job_id=job_id, expected_sections=expected_sections)


async def _process_job_async(job_id: str, settings: Settings) -> None:
  """Run a queued job in-process to update status as work progresses."""
  from app.jobs.worker import JobProcessor

  # Fetch the queued record so we can process only if it still exists.
  repo = _get_jobs_repo(settings)
  record = await run_in_threadpool(repo.get_job, job_id)

  if record is None:
    return

  # Run the job with a fresh processor to update progress states.
  processor = JobProcessor(jobs_repo=repo, orchestrator=_get_orchestrator(settings), settings=settings)
  # Execute the job asynchronously so progress updates stream back to storage.
  await processor.process_job(record)


def _log_job_task_failure(task: asyncio.Task[None]) -> None:
  """Log unexpected failures from background job tasks."""

  try:
    task.result()
  except Exception as exc:  # noqa: BLE001
    logger.error("Job processing task failed: %s", exc, exc_info=True)


def _kickoff_job_processing(
  background_tasks: BackgroundTasks, job_id: str, settings: Settings, job_worker_active: bool = False
) -> None:
  """Schedule background processing so clients see status updates."""

  # Fire-and-forget processing to keep the API responsive.
  # Skip in-process execution when external workers (Lambda) are responsible.
  if not settings.jobs_auto_process:
    return

  # Defer to the shared worker loop to avoid duplicate processing.
  # Note: Caller is responsible for passing job_worker_active status to avoid circular dependency
  if job_worker_active:
    return

  # Prefer immediate scheduling on the running loop to start work right away.
  try:
    loop = asyncio.get_running_loop()
  except RuntimeError:
    background_tasks.add_task(_process_job_async, job_id, settings)
    return

  task = loop.create_task(_process_job_async(job_id, settings))
  task.add_done_callback(_log_job_task_failure)
