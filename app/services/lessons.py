from __future__ import annotations

import json
import logging
import time

from app.api.models import GenerateLessonRequest, GenerateLessonResponse, LessonMeta
from app.config import Settings
from app.jobs.progress import build_call_plan
from app.notifications.factory import build_notification_service
from app.schema.quotas import QuotaPeriod
from app.schema.sql import User
from app.services.audit import log_llm_interaction
from app.services.feature_flags import is_feature_enabled
from app.services.model_routing import _get_orchestrator, _resolve_model_selection
from app.services.quota_buckets import QuotaExceededError, consume_quota, get_quota_snapshot
from app.services.request_validation import _resolve_learner_level, _resolve_primary_language
from app.services.runtime_config import resolve_effective_runtime_config
from app.storage.factory import _get_repo
from app.storage.lessons_repo import LessonRecord
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
OptionalStr = str | None
OptionalInt = int | None


async def process_lesson_generation(
  request: GenerateLessonRequest, lesson_id: str, settings: Settings, current_user: User, db_session: AsyncSession, tier_id: int, idempotency_key: OptionalStr = None, job_id: OptionalStr = None, section_cap: OptionalInt = None
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

  # Enforce monthly section quotas at generation time so queued jobs cannot exceed updated tier limits.
  runtime_config = await resolve_effective_runtime_config(db_session, settings=settings, org_id=current_user.org_id, subscription_tier_id=tier_id, user_id=None)
  sections_per_month = int(runtime_config.get("limits.sections_per_month") or 0)
  if sections_per_month <= 0:
    raise QuotaExceededError("section.generate quota disabled")
  section_snapshot = await get_quota_snapshot(db_session, user_id=current_user.id, metric_key="section.generate", period=QuotaPeriod.MONTH, limit=sections_per_month)
  if section_snapshot.remaining <= 0:
    raise QuotaExceededError("section.generate quota exceeded")
  plan = build_call_plan(request.model_dump(mode="python", by_alias=True))
  requested_sections = int(plan.depth)
  effective_sections = min(int(requested_sections), int(section_snapshot.remaining))
  if section_cap is not None:
    effective_sections = min(int(effective_sections), int(section_cap))
  if effective_sections <= 0:
    raise QuotaExceededError("section.generate quota exceeded")
  section_filter = None
  if effective_sections < requested_sections:
    section_filter = set(range(1, int(effective_sections) + 1))
  # Track consumption to avoid double counting within a single orchestration run.
  consumed_indexes: set[int] = set()

  async def _progress_callback(phase: str, subphase: str | None, messages: list[str] | None = None, advance: bool = True, partial_json: dict | None = None, section_progress=None) -> None:  # noqa: ANN001
    # Consume quota on section completion so usage reflects actual generated output.
    if section_progress is None:
      return
    if getattr(section_progress, "status", None) != "completed":
      return
    idx = int(getattr(section_progress, "index", -1))
    if idx < 0:
      return
    if idx in consumed_indexes:
      return
    consumed_indexes.add(idx)
    await consume_quota(db_session, user_id=current_user.id, metric_key="section.generate", period=QuotaPeriod.MONTH, quantity=1, limit=sections_per_month, metadata={"job_id": job_id, "lesson_id": lesson_id, "section_index": idx})

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
    progress_callback=_progress_callback,
    section_filter=section_filter,
  )

  if current_user.id:
    total_tokens = 0
    if result.usage:
      for entry in result.usage:
        total_tokens += int(entry.get("prompt_tokens", 0)) + int(entry.get("completion_tokens", 0))

    await log_llm_interaction(user_id=current_user.id, model_name=f"planner:{planner_model},section_builder:{section_builder_model}", prompt_summary=request.topic, tokens_used=total_tokens, status="completed", session=db_session)

  latency_ms = int((time.monotonic() - start) * 1000)

  logs = list(result.logs)
  if section_filter is not None:
    # Surface quota capping to clients so they can explain partial output clearly.
    logs.append(f"Quota cap applied: generated {effective_sections} section(s) (requested {requested_sections}).")

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
    idempotency_key=idempotency_key or request.idempotency_key,
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
    logs=logs,  # Include logs from orchestrator plus quota capping when applied.
  )
