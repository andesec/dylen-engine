"""Jobs endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.deps import _require_dev_key
from app.api.models import (
  GenerateLessonRequest,
  JobCreateResponse,
  JobRetryRequest,
  JobStatusResponse,
  WritingCheckRequest,
)
from app.config import Settings, get_settings
from app.core.lifespan import is_job_worker_active
from app.services.jobs import (
  _DATE_FORMAT,
  _JOB_NOT_FOUND_MSG,
  _create_job_record,
  _expected_sections_from_request,
  _job_status_from_record,
  _kickoff_job_processing,
  _parse_job_request,
)
from app.storage.factory import _get_jobs_repo

router = APIRouter()


@router.post("/v1/jobs", response_model=JobCreateResponse, dependencies=[Depends(_require_dev_key)])
async def create_job(
  request: GenerateLessonRequest,
  background_tasks: BackgroundTasks,
  settings: Settings = Depends(get_settings),
) -> JobCreateResponse:
  """Create a background lesson generation job."""
  response = await _create_job_record(request, settings)

  # Kick off processing so the client can poll for status immediately.
  _kickoff_job_processing(
    background_tasks, response.job_id, settings, job_worker_active=is_job_worker_active()
  )
  return response


@router.post(
  "/v1/lessons/jobs", response_model=JobCreateResponse, dependencies=[Depends(_require_dev_key)]
)
async def create_lesson_job(
  request: GenerateLessonRequest,
  background_tasks: BackgroundTasks,
  settings: Settings = Depends(get_settings),
) -> JobCreateResponse:
  """Alias route for creating a background lesson generation job."""
  response = await _create_job_record(request, settings)

  # Kick off processing so the client can poll for status immediately.
  _kickoff_job_processing(
    background_tasks, response.job_id, settings, job_worker_active=is_job_worker_active()
  )
  return response


@router.get(
  "/v1/jobs/{job_id}", response_model=JobStatusResponse, dependencies=[Depends(_require_dev_key)]
)
async def get_job_status(
  job_id: str, settings: Settings = Depends(get_settings)
) -> JobStatusResponse:
  """Fetch the status and result of a background job."""
  repo = _get_jobs_repo(settings)
  record = await run_in_threadpool(repo.get_job, job_id)

  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  return _job_status_from_record(record, settings)


@router.post(
  "/v1/jobs/{job_id}/cancel",
  response_model=JobStatusResponse,
  dependencies=[Depends(_require_dev_key)],
)
async def cancel_job(job_id: str, settings: Settings = Depends(get_settings)) -> JobStatusResponse:
  """Request cancellation of a running background job."""
  repo = _get_jobs_repo(settings)
  record = await run_in_threadpool(repo.get_job, job_id)

  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)

  if record.status in ("done", "error", "canceled"):
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT,
      detail="Job is already finalized and cannot be canceled.",
    )

  updated = await run_in_threadpool(
    repo.update_job,
    job_id,
    status="canceled",
    phase="canceled",
    subphase=None,
    progress=100.0,
    logs=record.logs + ["Job cancellation requested by client."],
    completed_at=time.strftime(_DATE_FORMAT, time.gmtime()),
  )

  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  return _job_status_from_record(updated, settings)


@router.post(
  "/v1/jobs/{job_id}/retry",
  response_model=JobStatusResponse,
  dependencies=[Depends(_require_dev_key)],
)
async def retry_job(
  job_id: str,
  payload: JobRetryRequest,
  background_tasks: BackgroundTasks,
  settings: Settings = Depends(get_settings),
) -> JobStatusResponse:
  """Retry a failed job with optional section/agent targeting."""
  repo = _get_jobs_repo(settings)
  record = await run_in_threadpool(repo.get_job, job_id)

  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)

  # Only finalized failures should be eligible for retry.
  if record.status not in ("error", "canceled"):
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT,
      detail="Only failed or canceled jobs can be retried.",
    )

  # Enforce the retry limit to avoid unbounded reprocessing.
  retry_count = record.retry_count or 0
  max_retries = record.max_retries if record.max_retries is not None else settings.job_max_retries

  if retry_count >= max_retries:
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT, detail="Retry limit reached for this job."
    )

  # Resolve expected sections for validation against retry targets.
  try:
    parsed_request = _parse_job_request(record.request)
  except ValidationError as exc:
    raise HTTPException(
      status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
      detail="Stored job request failed validation.",
    ) from exc

  if isinstance(parsed_request, WritingCheckRequest):
    if payload.sections or payload.agents:
      raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Writing check retries do not support section or agent targeting.",
      )
    expected_sections = 0
  else:
    expected_sections = record.expected_sections or _expected_sections_from_request(
      parsed_request, settings
    )

  # Normalize retry sections to a unique, ordered list.
  retry_sections = None

  if payload.sections:
    # Ensure retry section indexes are within expected bounds.
    invalid = [index for index in payload.sections if index >= expected_sections]

    if invalid:
      raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Retry section indexes exceed expected section count.",
      )
    retry_sections = sorted(set(payload.sections))

  # Preserve agent order while deduplicating retry targets.
  retry_agents = list(dict.fromkeys(payload.agents)) if payload.agents else None
  logs = record.logs + [f"Retry attempt {retry_count + 1} queued."]

  # Requeue the job with retry metadata so the worker can resume.
  updated = await run_in_threadpool(
    repo.update_job,
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

  # Kick off processing so retries start immediately when auto-processing is enabled.
  _kickoff_job_processing(
    background_tasks, updated.job_id, settings, job_worker_active=is_job_worker_active()
  )
  return _job_status_from_record(updated, settings)
