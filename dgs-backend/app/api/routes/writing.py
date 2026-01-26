import time

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models import JobCreateResponse, WritingCheckRequest
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.api.deps import consume_section_quota
from app.jobs.models import JobRecord
from app.schema.sql import User
from app.services.audit import log_llm_interaction
from app.services.jobs import trigger_job_processing
from app.services.request_validation import _validate_writing_request
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id

router = APIRouter()

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _compute_job_ttl(settings: Settings) -> int | None:
  if settings.jobs_ttl_seconds is None:
    return None
  return int(time.time()) + settings.jobs_ttl_seconds


@router.post("/check", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_writing_check(  # noqa: B008
  request: WritingCheckRequest,
  background_tasks: BackgroundTasks,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
  _ = Depends(consume_section_quota),  # noqa: B008
) -> JobCreateResponse:
  """Create a background job to check a writing task response."""

  if current_user.id:
    await log_llm_interaction(user_id=current_user.id, model_name="writing-check", prompt_summary=f"Writing check for: {request.text[:50]}...", status="queued", session=db_session)

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
  await repo.create_job(record)
  response = JobCreateResponse(job_id=job_id, expected_sections=0)

  # Kick off processing so the client can poll for status immediately.
  trigger_job_processing(background_tasks, response.job_id, settings)

  return response
