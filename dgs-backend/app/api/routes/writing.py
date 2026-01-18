import time

from fastapi import APIRouter, BackgroundTasks, Depends, status
from starlette.concurrency import run_in_threadpool

from app.api.deps import require_dev_key
from app.api.models import JobCreateResponse, WritingCheckRequest
from app.api.routes.jobs import kickoff_job_processing
from app.config import Settings, get_settings
from app.jobs.models import JobRecord
from app.services.request_validation import _validate_writing_request
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id

router = APIRouter()

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _compute_job_ttl(settings: Settings) -> int | None:
  if settings.jobs_ttl_seconds is None:
    return None
  return int(time.time()) + settings.jobs_ttl_seconds


@router.post("/check", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_dev_key)])
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
  kickoff_job_processing(background_tasks, response.job_id, settings)

  return response
