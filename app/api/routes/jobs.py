import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models import GenerateLessonRequest, JobCreateResponse, JobRetryRequest, JobStatusResponse
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.schema.sql import User
from app.services import jobs as job_service

router = APIRouter()
logger = logging.getLogger("app.api.routes.jobs")


@router.post("", response_model=JobCreateResponse)
async def create_job(  # noqa: B008
  request: GenerateLessonRequest,
  background_tasks: BackgroundTasks,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
) -> JobCreateResponse:
  """Create a background lesson generation job."""
  return await job_service.create_job(request, settings, background_tasks, db_session, user_id=str(current_user.id))


@router.post("/{job_id}/retry", response_model=JobStatusResponse)
async def retry_job(  # noqa: B008
  job_id: str,
  payload: JobRetryRequest,
  background_tasks: BackgroundTasks,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
) -> JobStatusResponse:
  """Retry a failed job with optional section/agent targeting."""
  return await job_service.retry_job(job_id, payload, settings, background_tasks)


@router.post("/{job_id}/cancel", response_model=JobStatusResponse)
async def cancel_job(  # noqa: B008
  job_id: str,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
) -> JobStatusResponse:
  """Request cancellation of a running background job."""
  return await job_service.cancel_job(job_id, settings)


@router.get("/{job_id}", response_model=JobStatusResponse, dependencies=[Depends(get_current_active_user)])
async def get_job_status(  # noqa: B008
  job_id: str,
  settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobStatusResponse:
  """Fetch the status and result of a background job."""
  return await job_service.get_job_status(job_id, settings)
