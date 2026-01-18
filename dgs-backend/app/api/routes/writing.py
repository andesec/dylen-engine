"""Writing check endpoints."""

from __future__ import annotations

import time
from fastapi import APIRouter, BackgroundTasks, Depends, status
from starlette.concurrency import run_in_threadpool
from app.config import Settings, get_settings
from app.api.deps import _require_dev_key
from app.api.models import WritingCheckRequest, JobCreateResponse
from app.jobs.models import JobRecord
from app.storage.factory import _get_jobs_repo
from app.services.validation import _validate_writing_request
from app.services.jobs import _compute_job_ttl, _kickoff_job_processing
from app.utils.ids import generate_job_id
from app.core.lifespan import is_job_worker_active

router = APIRouter()
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@router.post(
  "/v1/writing/check",
  response_model=JobCreateResponse,
  status_code=status.HTTP_202_ACCEPTED,
  dependencies=[Depends(_require_dev_key)],
)
async def create_writing_check(  # noqa: B008
    request: WritingCheckRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobCreateResponse:
  """Create a background job to check a writing task response."""
  _validate_writing_request(request)
  repo = _get_jobs_repo(settings)
  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())

  record = JobRecord(
    job_id=job_id,
    request=request.model_dump(mode="python"),
    status="queued",
    phase="queued",
    expected_sections=0,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=settings.job_max_retries,
    retry_sections=None,
    retry_agents=None,
    created_at=timestamp,
    updated_at=timestamp,
    ttl=_compute_job_ttl(settings),
  )
  await run_in_threadpool(repo.create_job, record)
  response = JobCreateResponse(job_id=job_id, expected_sections=0)

  # Kick off processing so the client can poll for status immediately.
  _kickoff_job_processing(background_tasks, response.job_id, settings, job_worker_active=is_job_worker_active())

  return response
