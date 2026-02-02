from __future__ import annotations

import json
import logging
import time

from app.api.models import GenerateLessonRequest, GenerateLessonResponse, LessonMeta
from app.config import Settings
from app.notifications.factory import build_notification_service
from app.schema.sql import User
from app.services.audit import log_llm_interaction
from app.services.feature_flags import is_feature_enabled
from app.services.model_routing import _get_orchestrator, _resolve_model_selection
from app.services.request_validation import _resolve_learner_level, _resolve_primary_language
from app.storage.factory import _get_repo
from app.storage.lessons_repo import LessonRecord
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


async def process_lesson_generation(
  request: GenerateLessonRequest,
  lesson_id: str,
  settings: Settings,
  current_user: User,
  db_session: AsyncSession,
  tier_id: int,
  idempotency_key: str | None = None,
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
    logs=result.logs,  # Include logs from orchestrator
  )
