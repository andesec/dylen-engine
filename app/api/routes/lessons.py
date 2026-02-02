from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import consume_section_quota
from app.api.deps_concurrency import verify_concurrency
from app.api.models import GenerateLessonRequest, GenerateLessonResponse, JobCreateResponse, LessonCatalogResponse, LessonJobResponse, LessonMeta, LessonRecordResponse, OrchestrationFailureResponse, ValidationResponse
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.jobs.models import JobRecord
from app.jobs.progress import build_call_plan
from app.schema.lesson_catalog import build_lesson_catalog
from app.schema.sql import User
from app.schema.validate_lesson import validate_lesson
from app.services.jobs import create_job
from app.services.request_validation import _validate_generate_request
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.tasks.factory import get_task_enqueuer
from app.services.users import get_user_subscription_tier
from app.storage.factory import _get_jobs_repo, _get_repo
from app.utils.ids import generate_job_id, generate_lesson_id

router = APIRouter()
logger = logging.getLogger(__name__)

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@router.get("/catalog", response_model=LessonCatalogResponse)
async def get_lesson_catalog(response: Response, settings: Settings = Depends(get_settings), db_session: AsyncSession = Depends(get_db)) -> LessonCatalogResponse:  # noqa: B008
  """Return blueprint, teaching style, and widget metadata for clients."""
  # Toggle cache control with DB-backed config so operators can refresh dynamically.
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=None, subscription_tier_id=None)
  if runtime_config.get("lessons.cache_catalog") is True:
    response.headers["Cache-Control"] = "public, max-age=86400"
  # Build a static payload so the client can cache the response safely.
  payload = build_lesson_catalog(settings)
  return LessonCatalogResponse(**payload)


@router.post("/validate", response_model=ValidationResponse)
async def validate_endpoint(payload: dict[str, Any]) -> ValidationResponse:
  """Validate lesson payloads from stored lessons or job results against schema and widgets."""

  ok, errors, _model = validate_lesson(payload)
  return ValidationResponse(ok=ok, errors=errors)


@router.post("/generate", response_model=LessonJobResponse, status_code=status.HTTP_202_ACCEPTED, responses={500: {"model": OrchestrationFailureResponse}})
async def generate_lesson(  # noqa: B008
  request: GenerateLessonRequest,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
  quota_check=Depends(consume_section_quota),  # noqa: B008
  concurrency_check=Depends(verify_concurrency("lesson")),  # noqa: B008
) -> LessonJobResponse:
  """Generate a lesson from a topic using the asynchronous pipeline."""
  tier_id, _tier_name = await get_user_subscription_tier(db_session, current_user.id)
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=current_user.org_id, subscription_tier_id=tier_id)
  _validate_generate_request(request, settings, max_topic_length=runtime_config.get("limits.max_topic_length"))

  jobs_repo = _get_jobs_repo(settings)

  # Idempotency Check: Return existing job info if key matches.
  if request.idempotency_key:
    existing_job = await jobs_repo.find_by_idempotency_key(request.idempotency_key)
    if existing_job and existing_job.user_id == str(current_user.id):
      logger.info("Found existing job %s for idempotency key %s", existing_job.job_id, request.idempotency_key)

      lesson_id = existing_job.request.get("_lesson_id")

      # If completed, check result
      if existing_job.status == "done" and existing_job.result_json:
        # If we have the result, we can try to extract lesson_id if not in request meta
        if not lesson_id:
            try:
                res = GenerateLessonResponse.model_validate(existing_job.result_json)
                lesson_id = res.lesson_id
            except Exception:
                pass

        if lesson_id:
             return LessonJobResponse(job_id=existing_job.job_id, expected_sections=existing_job.expected_sections or 0, lesson_id=lesson_id)

      # If still processing or queued, we return the job info if we have lesson_id
      if lesson_id:
          return LessonJobResponse(job_id=existing_job.job_id, expected_sections=existing_job.expected_sections or 0, lesson_id=lesson_id)

      # If we can't find lesson_id, we might need to error or create new?
      # Assuming idempotency key means "same result", so if we can't give same result, it's a problem.
      # But for now, let's fall through if we really can't find it (which shouldn't happen for new jobs).
      if existing_job.status in ("queued", "processing", "in_progress"):
           raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A request with this idempotency key is already being processed.")

  # Generate IDs
  lesson_id = generate_lesson_id()
  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  # Set TTL to 1 hour
  job_ttl = int(time.time()) + 3600

  # Expected sections
  plan = build_call_plan(request.model_dump(mode="python", by_alias=True))
  expected_sections = plan.depth

  # Save Job
  request_payload = request.model_dump(mode="python", by_alias=True)
  request_payload["_lesson_id"] = lesson_id  # Store lesson_id for retrieval

  job_record = JobRecord(
    job_id=job_id,
    user_id=str(current_user.id),
    request=request_payload,
    status="queued",
    target_agent="lesson",  # Mark as lesson job
    phase="queued",
    created_at=timestamp,
    updated_at=timestamp,
    expected_sections=expected_sections,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=settings.job_max_retries,
    logs=[],
    progress=0.0,
    ttl=job_ttl,
    idempotency_key=request.idempotency_key,
  )
  await jobs_repo.create_job(job_record)

  # Enqueue Task
  enqueuer = get_task_enqueuer(settings)

  # Params for worker
  params = request.model_dump(mode="python", by_alias=True)

  try:
    await enqueuer.enqueue_lesson(lesson_id=lesson_id, job_id=job_id, params=params, user_id=str(current_user.id))
  except Exception as e:
    logger.error("Failed to enqueue lesson task: %s", e, exc_info=True)
    # Mark job as error so it doesn't stay queued forever
    await jobs_repo.update_job(job_id, status="error", phase="error", logs=[f"Enqueue failed: {e!s}"], completed_at=time.strftime(_DATE_FORMAT, time.gmtime()))
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to enqueue lesson generation task.") from e

  return LessonJobResponse(job_id=job_id, expected_sections=expected_sections, lesson_id=lesson_id)


@router.get("/{lesson_id}", response_model=LessonRecordResponse)
async def get_lesson(  # noqa: B008
  lesson_id: str,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
) -> LessonRecordResponse:
  """Fetch a stored lesson by identifier, consistent with async job persistence."""
  repo = _get_repo(settings)
  record = await repo.get_lesson(lesson_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")

  if record.user_id != str(current_user.id):
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

  lesson_json = json.loads(record.lesson_json)
  return LessonRecordResponse(
    lesson_id=record.lesson_id,
    topic=record.topic,
    title=record.title,
    created_at=record.created_at,
    schema_version=record.schema_version,
    prompt_version=record.prompt_version,
    lesson_json=lesson_json,
    meta=LessonMeta(provider_a=record.provider_a, model_a=record.model_a, provider_b=record.provider_b, model_b=record.model_b, latency_ms=record.latency_ms),
  )


@router.post("/jobs", response_model=JobCreateResponse)
async def create_lesson_job(  # noqa: B008
  request: GenerateLessonRequest,
  background_tasks: BackgroundTasks,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
  _=Depends(verify_concurrency("lesson")),  # noqa: B008
) -> JobCreateResponse:
  """Alias route for creating a background lesson generation job."""
  return await create_job(request, settings, background_tasks, db_session, user_id=str(current_user.id), target_agent="lesson")
