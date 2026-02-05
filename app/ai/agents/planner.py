"""Planner agent implementation."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import ValidationError

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import render_planner_prompt
from app.ai.errors import is_output_error
from app.ai.pipeline.contracts import GenerationRequest, JobContext, LessonPlan
from app.core.database import get_session_factory
from app.schema.quotas import QuotaPeriod
from app.services.quota_buckets import QuotaExceededError, commit_quota_reservation, release_quota_reservation, reserve_quota
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.telemetry.context import llm_call_context


def _repair_planner_json(plan_json: dict[str, Any]) -> dict[str, Any]:
  """Repair JSON by converting between strings and lists of strings."""

  if "sections" in plan_json:
    # Normalize list/string mismatches inside each section payload.

    for section in plan_json["sections"]:
      # Convert string to list for fields that should be lists

      for field in ["data_collection_points"]:
        if field in section and isinstance(section[field], str):
          section[field] = [section[field]]

      # Convert array to string for fields that should be strings.

      for field in ["data_collection_points", "continuity_note"]:
        for _k, v in section[field]:
          if isinstance(v, list):
            section[field] = ".".join(str(x) for x in v)

      # Handle subsections

      if "subsections" in section:
        for subsection in section["subsections"]:
          if "planned_widgets" in subsection and isinstance(subsection["planned_widgets"], str):
            subsection["planned_widgets"] = [subsection["planned_widgets"]]

  return plan_json


class PlannerAgent(BaseAgent[GenerationRequest, LessonPlan]):
  """Generate a lesson plan before gathering content."""

  name = "Planner"

  async def run(self, input_data: GenerationRequest, ctx: JobContext) -> LessonPlan:
    """Plan the lesson sections and per-section gather prompts."""
    logger = logging.getLogger(__name__)
    reservation_limit = 0
    reservation_active = False
    reservation_user_id: uuid.UUID | None = None

    # Resolve the user id from metadata so quota reservations are scoped correctly.
    raw_user_id = (ctx.metadata or {}).get("user_id")
    if not raw_user_id:
      raise RuntimeError("Planner missing user_id metadata for quota reservation.")
    try:
      reservation_user_id = uuid.UUID(str(raw_user_id))
    except ValueError as exc:
      raise RuntimeError("Planner received invalid user_id metadata.") from exc

    # Resolve runtime configuration to determine the weekly lesson quota limit.
    session_factory = get_session_factory()
    if session_factory is None:
      raise RuntimeError("Database session factory unavailable for quota reservation.")
    async with session_factory() as session:
      # Resolve the user and tier so runtime config can be enforced.
      user = await get_user_by_id(session, reservation_user_id)
      if user is None:
        raise RuntimeError("Planner quota reservation failed: user not found.")
      tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
      # Require settings in metadata so runtime config resolution remains deterministic.
      settings = (ctx.metadata or {}).get("settings")
      if settings is None:
        raise RuntimeError("Planner missing settings metadata for quota resolution.")
      runtime_config = await resolve_effective_runtime_config(session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
      reservation_limit = int(runtime_config.get("limits.lessons_per_week") or 0)
      if reservation_limit <= 0:
        raise QuotaExceededError("lesson.generate quota disabled")

    try:
      # Reserve weekly lesson quota before running the planner.
      async with session_factory() as session:
        await reserve_quota(session, user_id=reservation_user_id, metric_key="lesson.generate", period=QuotaPeriod.WEEK, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), metadata={"job_id": str(ctx.job_id)})
      reservation_active = True

      # Prefer deterministic fixtures during local/test runs.
      dummy_json = self._load_dummy_json()

      if dummy_json is not None:
        logger.info("Using deterministic dummy output for Planner")
        # Use deterministic fixture output when configured to avoid provider calls.
        plan = LessonPlan.model_validate(dummy_json)
        # Commit quota reservation once planning succeeds.
        async with session_factory() as session:
          await commit_quota_reservation(session, user_id=reservation_user_id, metric_key="lesson.generate", period=QuotaPeriod.WEEK, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), metadata={"job_id": str(ctx.job_id)})
        return plan

      # Build the prompt and schema to request a structured plan.
      prompt_text = render_planner_prompt(input_data)
      schema = LessonPlan.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")

      schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
      # Stamp the provider call with agent context for audit logging.
      with llm_call_context(agent=self.name, lesson_topic=input_data.topic, job_id=ctx.job_id, purpose="plan_lesson", call_index="1/1"):
        try:
          response = await self._model.generate_structured(prompt_text, schema)
        except Exception as exc:  # noqa: BLE001
          if not is_output_error(exc):
            raise
          # Retry the same request with the parser error appended.
          retry_prompt = self._build_json_retry_prompt(prompt_text=prompt_text, error=exc)
          retry_purpose = "plan_lesson_retry"
          retry_call_index = "retry/1"

          with llm_call_context(agent=self.name, lesson_topic=input_data.topic, job_id=ctx.job_id, purpose=retry_purpose, call_index=retry_call_index):
            response = await self._model.generate_structured(retry_prompt, schema)

          self._record_usage(agent=self.name, purpose=retry_purpose, call_index=retry_call_index, usage=response.usage)

      self._record_usage(agent=self.name, purpose="plan_lesson", call_index="1/1", usage=response.usage)
      plan_json = response.content

      try:
        plan = LessonPlan.model_validate(plan_json)
        logger.debug("Planner returned valid JSON")

      except ValidationError as exc:
        logger.error("Planner returned invalid JSON: %s", exc)
        logger.info("Attempting to repair the json")
        plan_json = _repair_planner_json(plan_json)
        plan = LessonPlan.model_validate(plan_json)
        logger.info("Repair succeeded")

      # Ensure we respect depth rules from the caller.
      if len(plan.sections) != input_data.section_count:
        message = f"Planner returned {len(plan.sections)} sections; expected {input_data.section_count}."
        logger.error(message)
        raise RuntimeError(message)

      # Commit quota reservation once planning succeeds.
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        commit_metadata = {"job_id": str(ctx.job_id)}
        await commit_quota_reservation(session, user_id=reservation_user_id, metric_key="lesson.generate", period=QuotaPeriod.WEEK, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), metadata=commit_metadata)

      return plan
    except Exception:  # noqa: BLE001
      # Release quota reservation when planner fails.
      logger.error("Planner failed during execution.", exc_info=True)
      if reservation_active and reservation_user_id is not None:
        try:
          async with session_factory() as session:
            # Build quota metadata for audit logging.
            release_metadata = {"job_id": str(ctx.job_id), "reason": "planner_failed"}
            await release_quota_reservation(session, user_id=reservation_user_id, metric_key="lesson.generate", period=QuotaPeriod.WEEK, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), metadata=release_metadata)
        except Exception:  # noqa: BLE001
          logger.error("Planner failed to release lesson quota reservation.", exc_info=True)
      raise
