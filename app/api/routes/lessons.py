from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import consume_section_quota
from app.api.deps_concurrency import verify_concurrency
from app.api.models import GenerateLessonRequest, GenerateLessonResponse, JobCreateResponse, LessonCatalogResponse, LessonMeta, LessonRecordResponse, OrchestrationFailureResponse, ValidationResponse
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.jobs.models import JobRecord
from app.notifications.factory import build_notification_service
from app.schema.lesson_catalog import build_lesson_catalog
from app.schema.sql import User
from app.schema.validate_lesson import validate_lesson
from app.services.audit import log_llm_interaction
from app.services.feature_flags import is_feature_enabled
from app.services.jobs import create_job
from app.services.model_routing import _get_orchestrator, _resolve_model_selection
from app.services.request_validation import _resolve_learner_level, _resolve_primary_language, _validate_generate_request
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.users import get_user_subscription_tier
from app.storage.factory import _get_jobs_repo, _get_repo
from app.storage.lessons_repo import LessonRecord
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


async def _process_lesson_generation(
  request: GenerateLessonRequest,
  settings: Settings,
  current_user: User,
  db_session: AsyncSession,
  tier_id: int,
) -> GenerateLessonResponse:
  """Execute core lesson generation logic."""
  start = time.monotonic()
  # Resolve per-agent model overrides and provider routing for this request.
  selection = _resolve_model_selection(settings, models=request.models)
  (section_builder_provider, section_builder_model, planner_provider, planner_model, repairer_provider, repairer_model) = selection
  orchestrator = _get_orchestrator(
    settings, section_builder_provider=section_builder_provider, section_builder_model=section_builder_model, planner_provider=planner_provider, planner_model=planner_model, repair_provider=repairer_provider, repair_model=repairer_model
  )
  language = _resolve_primary_language(request)
  learner_level = _resolve_learner_level(request)

  if current_user.id:
    await log_llm_interaction(user_id=current_user.id, model_name=f"planner:{planner_model},section_builder:{section_builder_model}", prompt_summary=request.topic, status="started", session=db_session)

  result = await orchestrator.generate_lesson(
    topic=request.topic,
    details=request.details,
    blueprint=request.blueprint,
    teaching_style=request.teaching_style,
    learner_level=learner_level,
    depth=request.depth,
    schema_version=request.schema_version or settings.schema_version,
    section_builder_model=section_builder_model,
    structured_output=True,
    language=language,
    widgets=request.widgets,
  )

  if current_user.id:
    total_tokens = 0
    if result.usage:
      for entry in result.usage:
        total_tokens += int(entry.get("prompt_tokens", 0)) + int(entry.get("completion_tokens", 0))

    await log_llm_interaction(user_id=current_user.id, model_name=f"planner:{planner_model},section_builder:{section_builder_model}", prompt_summary=request.topic, tokens_used=total_tokens, status="completed", session=db_session)

  lesson_id = generate_lesson_id()
  latency_ms = int((time.monotonic() - start) * 1000)

  record = LessonRecord(
    lesson_id=lesson_id,
    user_id=str(current_user.id),
    topic=request.topic,
    title=result.lesson_json["title"],
    created_at=time.strftime(_DATE_FORMAT, time.gmtime()),
    schema_version=request.schema_version or settings.schema_version,
    prompt_version=settings.prompt_version,
    provider_a=result.provider_a,
    model_a=result.model_a,
    provider_b=result.provider_b,
    model_b=result.model_b,
    lesson_json=json.dumps(result.lesson_json, ensure_ascii=True),
    status="ok",
    latency_ms=latency_ms,
    idempotency_key=request.idempotency_key,
  )

  repo = _get_repo(settings)
  await repo.create_lesson(record)
  # Notify the user after a successful persistence write.
  email_enabled = await is_feature_enabled(db_session, key="feature.notifications.email", org_id=current_user.org_id, subscription_tier_id=tier_id)
  await build_notification_service(settings, email_enabled=email_enabled).notify_lesson_generated(user_id=current_user.id, user_email=current_user.email, lesson_id=lesson_id, topic=request.topic)

  return GenerateLessonResponse(
    lesson_id=lesson_id,
    lesson_json=result.lesson_json,
    meta=LessonMeta(provider_a=result.provider_a, model_a=result.model_a, provider_b=result.provider_b, model_b=result.model_b, latency_ms=latency_ms),
    logs=result.logs,  # Include logs from orchestrator
  )


@router.post("/generate", response_model=GenerateLessonResponse, responses={500: {"model": OrchestrationFailureResponse}})
async def generate_lesson(  # noqa: B008
  request: GenerateLessonRequest,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
  quota_check=Depends(consume_section_quota),  # noqa: B008
  concurrency_check=Depends(verify_concurrency("lesson")),  # noqa: B008
) -> GenerateLessonResponse:
  """Generate a lesson from a topic using the two-step pipeline."""
  tier_id, _tier_name = await get_user_subscription_tier(db_session, current_user.id)
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=current_user.org_id, subscription_tier_id=tier_id)
  _validate_generate_request(request, settings, max_topic_length=runtime_config.get("limits.max_topic_length"))

  # Tracking job for concurrency
  jobs_repo = _get_jobs_repo(settings)

  tracking_job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  # Set TTL to 1 hour to prevent zombie jobs blocking concurrency forever
  job_ttl = int(time.time()) + 3600

  tracking_job = JobRecord(
    job_id=tracking_job_id,
    user_id=str(current_user.id),
    request=request.model_dump(mode="python", by_alias=True),
    status="processing",
    target_agent="lesson",  # Mark as lesson job
    phase="processing",
    created_at=timestamp,
    updated_at=timestamp,
    expected_sections=0,  # Not strictly tracked for sync
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=0,
    logs=[],
    progress=0.0,
    ttl=job_ttl,
  )
  await jobs_repo.create_job(tracking_job)

  try:
    response_payload = await _process_lesson_generation(request, settings, current_user, db_session, tier_id)

    # Mark tracking job as completed
    await jobs_repo.update_job(tracking_job_id, status="done", phase="done", progress=100.0, completed_at=time.strftime(_DATE_FORMAT, time.gmtime()), result_json=response_payload.model_dump(mode="json"))

    return response_payload
  except Exception as e:
    # Mark tracking job as error
    await jobs_repo.update_job(tracking_job_id, status="error", phase="error", logs=[str(e)], completed_at=time.strftime(_DATE_FORMAT, time.gmtime()))
    raise


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
