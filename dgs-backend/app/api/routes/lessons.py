import json
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_dev_key
from app.api.models import GenerateLessonRequest, GenerateLessonResponse, JobCreateResponse, LessonCatalogResponse, LessonMeta, LessonRecordResponse, OrchestrationFailureResponse, ValidationResponse
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.notifications.factory import build_notification_service
from app.schema.lesson_catalog import build_lesson_catalog
from app.schema.sql import User
from app.schema.validate_lesson import validate_lesson
from app.services.audit import log_llm_interaction
from app.services.jobs import create_job
from app.services.model_routing import _get_orchestrator, _resolve_model_selection
from app.services.request_validation import _resolve_learner_level, _resolve_primary_language, _validate_generate_request
from app.storage.factory import _get_repo
from app.storage.lessons_repo import LessonRecord
from app.utils.ids import generate_lesson_id

router = APIRouter()

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


@router.get("/catalog", response_model=LessonCatalogResponse)
async def get_lesson_catalog(response: Response, settings: Settings = Depends(get_settings)) -> LessonCatalogResponse:  # noqa: B008
  """Return blueprint, teaching style, and widget metadata for clients."""
  # Toggle cache control with an environment flag for dynamic refreshes.
  if settings.cache_lesson_catalog:
    response.headers["Cache-Control"] = "public, max-age=86400"
  # Build a static payload so the client can cache the response safely.
  payload = build_lesson_catalog(settings)
  return LessonCatalogResponse(**payload)


@router.post("/validate", response_model=ValidationResponse, dependencies=[Depends(require_dev_key)])
async def validate_endpoint(payload: dict[str, Any]) -> ValidationResponse:
  """Validate lesson payloads from stored lessons or job results against schema and widgets."""

  ok, errors, _model = validate_lesson(payload)
  return ValidationResponse(ok=ok, errors=errors)


@router.post("/generate", response_model=GenerateLessonResponse, responses={500: {"model": OrchestrationFailureResponse}})
async def generate_lesson(  # noqa: B008
  request: GenerateLessonRequest,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
) -> GenerateLessonResponse:
  """Generate a lesson from a topic using the two-step pipeline."""
  _validate_generate_request(request, settings)

  start = time.monotonic()
  # Resolve per-agent model overrides and provider routing for this request.
  selection = _resolve_model_selection(settings, models=request.models)
  (gatherer_provider, gatherer_model, planner_provider, planner_model, structurer_provider, structurer_model, repairer_provider, repairer_model) = selection
  orchestrator = _get_orchestrator(
    settings,
    gatherer_provider=gatherer_provider,
    gatherer_model=gatherer_model,
    planner_provider=planner_provider,
    planner_model=planner_model,
    structurer_provider=structurer_provider,
    structurer_model=structurer_model,
    repair_provider=repairer_provider,
    repair_model=repairer_model,
  )
  language = _resolve_primary_language(request)
  learner_level = _resolve_learner_level(request)

  if current_user.id:
    await log_llm_interaction(user_id=current_user.id, model_name=f"planner:{planner_model},gatherer:{gatherer_model},structurer:{structurer_model}", prompt_summary=request.topic, status="started", session=db_session)

  result = await orchestrator.generate_lesson(
    topic=request.topic,
    details=request.details,
    blueprint=request.blueprint,
    teaching_style=request.teaching_style,
    learner_level=learner_level,
    depth=request.depth,
    schema_version=request.schema_version or settings.schema_version,
    structurer_model=structurer_model,
    gatherer_model=gatherer_model,
    structured_output=True,
    language=language,
    widgets=request.widgets,
  )

  if current_user.id:
    total_tokens = 0
    if result.usage:
      for entry in result.usage:
        total_tokens += int(entry.get("prompt_tokens", 0)) + int(entry.get("completion_tokens", 0))

    await log_llm_interaction(user_id=current_user.id, model_name=f"planner:{planner_model},gatherer:{gatherer_model},structurer:{structurer_model}", prompt_summary=request.topic, tokens_used=total_tokens, status="completed", session=db_session)

  lesson_id = generate_lesson_id()
  latency_ms = int((time.monotonic() - start) * 1000)

  record = LessonRecord(
    lesson_id=lesson_id,
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
  await build_notification_service(settings).notify_lesson_generated(user_id=current_user.id, user_email=current_user.email, lesson_id=lesson_id, topic=request.topic)

  return GenerateLessonResponse(
    lesson_id=lesson_id,
    lesson_json=result.lesson_json,
    meta=LessonMeta(provider_a=result.provider_a, model_a=result.model_a, provider_b=result.provider_b, model_b=result.model_b, latency_ms=latency_ms),
    logs=result.logs,  # Include logs from orchestrator
  )


@router.get("/{lesson_id}", response_model=LessonRecordResponse, dependencies=[Depends(require_dev_key)])
async def get_lesson(  # noqa: B008
  lesson_id: str,
  settings: Settings = Depends(get_settings),  # noqa: B008
) -> LessonRecordResponse:
  """Fetch a stored lesson by identifier, consistent with async job persistence."""
  repo = _get_repo(settings)
  record = await repo.get_lesson(lesson_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")

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
) -> JobCreateResponse:
  """Alias route for creating a background lesson generation job."""
  return await create_job(request, settings, background_tasks, db_session, user_id=str(current_user.id))
