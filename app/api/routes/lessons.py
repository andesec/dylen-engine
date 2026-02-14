from __future__ import annotations

import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline.contracts import GenerationRequest
from app.api.deps_concurrency import check_concurrency_limit
from app.api.models import (
  GenerateLessonRequest,
  GenerateLessonResponse,
  GenerateOutcomesRequest,
  JobCreateRequest,
  JobCreateResponse,
  LessonCatalogResponse,
  LessonJobResponse,
  LessonOutlineResponse,
  LessonRecordResponse,
  OrchestrationFailureResponse,
  SectionOutline,
  SectionSummary,
)
from app.config import Settings, get_settings
from app.core.database import get_db
from app.core.security import get_current_active_user, require_permission
from app.jobs.models import JobRecord
from app.jobs.progress import build_call_plan
from app.schema.lesson_catalog import build_lesson_catalog
from app.schema.lesson_requests import LessonRequest
from app.schema.outcomes import OutcomesAgentResponse
from app.schema.quotas import QuotaPeriod
from app.schema.sql import User
from app.services.jobs import create_job
from app.services.outcomes import generate_lesson_outcomes
from app.services.quota_buckets import QuotaExceededError, consume_quota, get_quota_snapshot, refund_quota
from app.services.request_validation import _validate_generate_request
from app.services.runtime_config import get_outcomes_model, resolve_effective_runtime_config
from app.services.tasks.factory import get_task_enqueuer
from app.services.users import get_user_subscription_tier
from app.services.widget_entitlements import validate_widget_entitlements
from app.storage.factory import _get_jobs_repo, _get_repo
from app.utils.ids import generate_job_id, generate_lesson_id

router = APIRouter()
logger = logging.getLogger(__name__)

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_DEFAULT_PAGE = 1
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 100


@router.get("", response_model=list[LessonRecordResponse], dependencies=[Depends(require_permission("lesson:list_own"))])
async def list_lessons(
  settings: Settings = Depends(get_settings),
  current_user: User = Depends(get_current_active_user),
  page: Annotated[int, Query(ge=1)] = _DEFAULT_PAGE,
  limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
  status: str | None = None,
  topic: str | None = None,
  sort_by: str = Query("created_at"),
  sort_order: str = Query("desc"),
) -> list[LessonRecordResponse]:
  """List lessons for the current user with pagination, filtering, and sorting."""
  repo = _get_repo(settings)

  lessons, _total = await repo.list_lessons(page=page, limit=limit, user_id=str(current_user.id), status=status, topic=topic, sort_by=sort_by, sort_order=sort_order)

  response = []
  for record in lessons:
    sections = await repo.list_sections(record.lesson_id)
    section_summaries = [SectionSummary(section_id=s.section_id, title=s.title, status=s.status) for s in sections]
    response.append(LessonRecordResponse(lesson_id=record.lesson_id, topic=record.topic, title=record.title, created_at=record.created_at, sections=section_summaries))

  return response


@router.get("/catalog", response_model=LessonCatalogResponse)
async def get_lesson_catalog(response: Response, settings: Settings = Depends(get_settings), db_session: AsyncSession = Depends(get_db)) -> LessonCatalogResponse:  # noqa: B008
  """Return blueprint, teaching style, and widget metadata for clients."""
  # Toggle cache control with DB-backed config so operators can refresh dynamically.
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=None, subscription_tier_id=None, user_id=None)
  if runtime_config.get("lessons.cache_catalog") is True:
    response.headers["Cache-Control"] = "public, max-age=86400"
  # Build a static payload so the client can cache the response safely.
  payload = build_lesson_catalog(settings)
  return LessonCatalogResponse(**payload)


@router.post("/outcomes", response_model=OutcomesAgentResponse, dependencies=[Depends(require_permission("lesson:outcomes"))])
async def generate_outcomes_endpoint(  # noqa: B008
  request: GenerateOutcomesRequest,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
) -> OutcomesAgentResponse:
  """Return a topic safety decision and a small set of learning outcomes."""
  # Enforce lesson concurrency after request validation to fail malformed bodies before DB-heavy checks.
  await check_concurrency_limit("lesson", current_user, db_session)
  tier_id, _tier_name = await get_user_subscription_tier(db_session, current_user.id)
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=None)
  # Deny-by-default: if lesson generation is disabled for this user, outcomes preflight is also disabled.
  validate_widget_entitlements(request.widgets, runtime_config=runtime_config)
  lessons_per_week = int(runtime_config.get("limits.lessons_per_week") or 0)
  sections_per_month = int(runtime_config.get("limits.sections_per_month") or 0)
  if lessons_per_week <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "lesson.generate"})
  if sections_per_month <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "section.generate"})
  lesson_snapshot = await get_quota_snapshot(db_session, user_id=current_user.id, metric_key="lesson.generate", period=QuotaPeriod.WEEK, limit=lessons_per_week)
  if lesson_snapshot.remaining <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "lesson.generate"})
  section_snapshot = await get_quota_snapshot(db_session, user_id=current_user.id, metric_key="section.generate", period=QuotaPeriod.MONTH, limit=sections_per_month)
  if section_snapshot.remaining <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "section.generate"})
  outcomes_checks_per_week = int(runtime_config.get("limits.outcomes_checks_per_week") or lessons_per_week)
  if outcomes_checks_per_week <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "lesson.outcomes_check"})
  snapshot = await get_quota_snapshot(db_session, user_id=current_user.id, metric_key="lesson.outcomes_check", period=QuotaPeriod.WEEK, limit=outcomes_checks_per_week)
  if snapshot.remaining <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "lesson.outcomes_check"})

  _validate_generate_request(request, settings, max_topic_length=runtime_config.get("limits.max_topic_length"))

  job_id = generate_job_id()
  # Reserve quota before calling the model so repeated requests cannot bypass quota enforcement.
  try:
    await consume_quota(db_session, user_id=current_user.id, metric_key="lesson.outcomes_check", period=QuotaPeriod.WEEK, quantity=1, limit=outcomes_checks_per_week, metadata={"job_id": job_id})
  except QuotaExceededError:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "lesson.outcomes_check"}) from None

  # Route outcomes through the dedicated outcomes provider/model by default; operators can override per-tenant.
  provider, model_name = get_outcomes_model(runtime_config)
  max_outcomes = int(runtime_config.get("limits.max_outcomes") or 5)
  # Clamp invalid operator configuration to a safe range.
  if max_outcomes <= 0:
    max_outcomes = 5
  if max_outcomes > 8:
    max_outcomes = 8

  generation_request = GenerationRequest(
    topic=request.topic,
    prompt=request.details,
    depth=request.depth,
    section_count=2,
    blueprint=request.blueprint,
    teaching_style=request.teaching_style,
    lesson_language=request.lesson_language,
    secondary_language=request.secondary_language,
    learner_level=request.learner_level,
    widgets=request.widgets,
  )
  try:
    payload, _model_used = await generate_lesson_outcomes(generation_request, settings=settings, provider=provider, model=str(model_name) if model_name else None, job_id=job_id, max_outcomes=max_outcomes)
  except Exception as exc:  # noqa: BLE001
    # Compensate quota reservation when the model call fails.
    try:
      await refund_quota(db_session, user_id=current_user.id, metric_key="lesson.outcomes_check", period=QuotaPeriod.WEEK, quantity=1, limit=outcomes_checks_per_week, metadata={"job_id": job_id, "reason": "outcomes_failed"})
    except Exception:  # noqa: BLE001
      pass
    logger.error("Outcomes generation failed: %s", exc, exc_info=True)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate outcomes.") from exc

  return payload


@router.post("/generate", response_model=LessonJobResponse, status_code=status.HTTP_202_ACCEPTED, responses={500: {"model": OrchestrationFailureResponse}}, dependencies=[Depends(require_permission("lesson:generate"))])
async def generate_lesson(  # noqa: B008
  request: GenerateLessonRequest,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
) -> LessonJobResponse:
  """Generate a lesson from a topic using the asynchronous pipeline."""
  if not request.idempotency_key:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="idempotency_key is required.")
  # Enforce lesson concurrency after request validation to fail malformed bodies before DB-heavy checks.
  await check_concurrency_limit("lesson", current_user, db_session)
  tier_id, _tier_name = await get_user_subscription_tier(db_session, current_user.id)
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=None)
  validate_widget_entitlements(request.widgets, runtime_config=runtime_config)
  # Enforce hard quotas before enqueueing work so invalid requests fail fast.
  lessons_per_week = int(runtime_config.get("limits.lessons_per_week") or 0)
  sections_per_month = int(runtime_config.get("limits.sections_per_month") or 0)
  if lessons_per_week <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "lesson.generate"})
  if sections_per_month <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "section.generate"})
  lesson_snapshot = await get_quota_snapshot(db_session, user_id=current_user.id, metric_key="lesson.generate", period=QuotaPeriod.WEEK, limit=lessons_per_week)
  if lesson_snapshot.remaining <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "lesson.generate"})
  section_snapshot = await get_quota_snapshot(db_session, user_id=current_user.id, metric_key="section.generate", period=QuotaPeriod.MONTH, limit=sections_per_month)
  if section_snapshot.remaining <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "section.generate"})
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
            logger.warning("Failed to recover lesson_id from existing job %s result.", existing_job.job_id)

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
  requested_sections = plan.depth
  capped_sections = min(int(section_snapshot.remaining), int(requested_sections))
  if capped_sections <= 0:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "QUOTA_EXCEEDED", "metric": "section.generate"})
  expected_sections = int(capped_sections)

  # Persist immutable lesson request context (including required outcomes) for downstream linkage.
  lesson_request = LessonRequest(
    creator_id=str(current_user.id),
    topic=request.topic,
    details=request.details,
    outcomes_json=list(request.outcomes),
    blueprint=request.blueprint,
    teaching_style_json=list(request.teaching_style),
    learner_level=request.learner_level,
    depth=request.depth,
    lesson_language=request.lesson_language,
    secondary_language=request.secondary_language,
    widgets_json=list(request.widgets) if request.widgets else None,
    status="queued",
    is_archived=False,
  )
  db_session.add(lesson_request)
  await db_session.flush()

  # Save Job
  request_payload = request.model_dump(mode="python", by_alias=True)
  request_payload["_lesson_id"] = lesson_id  # Store lesson_id for retrieval
  # Store quota caps in job metadata so the worker can enforce partial generation safely.
  meta = request_payload.get("_meta") if isinstance(request_payload.get("_meta"), dict) else {}
  meta = dict(meta)
  meta["user_id"] = str(current_user.id)
  meta["quota_cap_sections"] = expected_sections
  meta["lesson_request_id"] = int(lesson_request.id)
  request_payload["_meta"] = meta
  # Pre-populate job logs so clients can explain quota-capped jobs.
  job_logs: list[str] = []
  if expected_sections < requested_sections:
    job_logs.append(f"Quota cap applied: generating only {expected_sections} section(s) this month (requested {requested_sections}).")
  # Defer lesson quota reservation to the planner agent so reservations are scoped to agent execution.

  job_record = JobRecord(
    job_id=job_id,
    user_id=str(current_user.id),
    job_kind="lesson",
    request=request_payload,
    status="queued",
    lesson_id=lesson_id,
    target_agent="planner",
    phase="queued",
    created_at=timestamp,
    updated_at=timestamp,
    expected_sections=expected_sections,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    # Enforce strict retry limit to keep quota accounting deterministic.
    max_retries=0,
    logs=job_logs,
    progress=0.0,
    ttl=job_ttl,
    idempotency_key=request.idempotency_key or f"lesson-generate:{job_id}",
  )
  await jobs_repo.create_job(job_record)
  await db_session.commit()

  # Enqueue Task
  enqueuer = get_task_enqueuer(settings)

  try:
    await enqueuer.enqueue(job_id, {})
  except Exception as e:
    logger.error("Failed to enqueue lesson task: %s", e, exc_info=True)
    # Mark job as error so it doesn't stay queued forever (avoid leaking internal error details to clients).
    await jobs_repo.update_job(job_id, status="error", phase="error", logs=["Enqueue failed: TASK_ENQUEUE_FAILED"], completed_at=time.strftime(_DATE_FORMAT, time.gmtime()))
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to enqueue lesson generation task.") from e

  return LessonJobResponse(job_id=job_id, expected_sections=expected_sections, lesson_id=lesson_id)


@router.get("/{lesson_id}", response_model=LessonRecordResponse, dependencies=[Depends(require_permission("lesson:view_own"))])
async def get_lesson(  # noqa: B008
  lesson_id: uuid.UUID,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
) -> LessonRecordResponse:
  """Fetch a stored lesson by identifier, consistent with async job persistence."""
  lesson_id_str = str(lesson_id)
  repo = _get_repo(settings)
  record = await repo.get_lesson(lesson_id_str, user_id=str(current_user.id))
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")
  # Hide archived lessons from end users so retention rules are enforced server-side.
  if record.is_archived:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")

  sections = await repo.list_sections(lesson_id_str)

  section_summaries = [SectionSummary(section_id=s.section_id, title=s.title, status=s.status) for s in sections]

  return LessonRecordResponse(lesson_id=record.lesson_id, topic=record.topic, title=record.title, created_at=record.created_at, sections=section_summaries)


@router.get("/{lesson_id}/outline", response_model=LessonOutlineResponse, dependencies=[Depends(require_permission("lesson:outline_own"))])
async def get_lesson_outline(
  lesson_id: uuid.UUID,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
) -> LessonOutlineResponse:
  """Fetch the structured outline of a lesson from its plan."""
  lesson_id_str = str(lesson_id)
  repo = _get_repo(settings)
  record = await repo.get_lesson(lesson_id_str, user_id=str(current_user.id))
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")

  if not record.lesson_plan:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson outline not available.")

  plan = record.lesson_plan
  sections = []

  # Plan is stored as a dict (from model_dump)
  for s in plan.get("sections", []):
    subsections = [sub.get("title", "Untitled") for sub in s.get("subsections", [])]
    sections.append(SectionOutline(title=s.get("title", "Untitled"), subsections=subsections))

  return LessonOutlineResponse(lesson_id=record.lesson_id, topic=record.topic, title=record.title, sections=sections)


@router.post("/jobs", response_model=JobCreateResponse, dependencies=[Depends(require_permission("lesson:job_create"))])
async def create_lesson_job(  # noqa: B008
  request: GenerateLessonRequest,
  background_tasks: BackgroundTasks,
  settings: Settings = Depends(get_settings),  # noqa: B008
  current_user: User = Depends(get_current_active_user),  # noqa: B008
  db_session: AsyncSession = Depends(get_db),  # noqa: B008
) -> JobCreateResponse:
  """Alias route for creating a background lesson generation job."""
  # Validate request payloads at the route boundary before queue orchestration.
  tier_id, _tier_name = await get_user_subscription_tier(db_session, current_user.id)
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=None)
  validate_widget_entitlements(request.widgets, runtime_config=runtime_config)
  _validate_generate_request(request, settings, max_topic_length=runtime_config.get("limits.max_topic_length"))
  # Enforce lesson concurrency after request validation to fail malformed bodies before DB-heavy checks.
  await check_concurrency_limit("lesson", current_user, db_session)
  if not request.idempotency_key:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="idempotency_key is required.")
  lesson_id = generate_lesson_id()
  lesson_request = LessonRequest(
    creator_id=str(current_user.id),
    topic=request.topic,
    details=request.details,
    outcomes_json=list(request.outcomes),
    blueprint=request.blueprint,
    teaching_style_json=list(request.teaching_style),
    learner_level=request.learner_level,
    depth=request.depth,
    lesson_language=request.lesson_language,
    secondary_language=request.secondary_language,
    widgets_json=list(request.widgets) if request.widgets else None,
    status="queued",
    is_archived=False,
  )
  db_session.add(lesson_request)
  await db_session.flush()
  payload = request.model_dump(mode="python", by_alias=True)
  payload["_lesson_id"] = lesson_id
  payload["_meta"] = {"user_id": str(current_user.id), "lesson_request_id": int(lesson_request.id)}
  create_payload = JobCreateRequest(job_kind="lesson", target_agent="planner", idempotency_key=request.idempotency_key, payload=payload, lesson_id=lesson_id)
  await db_session.commit()
  return await create_job(create_payload, settings, background_tasks, db_session, user_id=str(current_user.id))
