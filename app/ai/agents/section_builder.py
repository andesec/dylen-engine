"""Section builder agent implementation."""

from __future__ import annotations

import logging
import uuid

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import render_section_builder_prompt
from app.ai.errors import is_output_error
from app.ai.pipeline.contracts import JobContext, PlanSection, StructuredSection
from app.core.database import get_session_factory
from app.schema.quotas import QuotaPeriod
from app.services.quota_buckets import QuotaExceededError, commit_quota_reservation, release_quota_reservation, reserve_quota
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.telemetry.context import llm_call_context


class SectionBuilder(BaseAgent[PlanSection, StructuredSection]):
  """Collect and structure a planned section in a single call."""

  name = "SectionBuilder"

  async def run(self, input_data: PlanSection, ctx: JobContext) -> StructuredSection:
    """Generate a structured section directly from the planner output."""
    logger = logging.getLogger(__name__)
    request = ctx.request
    reservation_limit = 0
    reservation_active = False
    reservation_user_id: uuid.UUID | None = None

    # Resolve the user id from metadata so quota reservations are scoped correctly.
    raw_user_id = (ctx.metadata or {}).get("user_id")
    if not raw_user_id:
      raise RuntimeError("SectionBuilder missing user_id metadata for quota reservation.")
    try:
      reservation_user_id = uuid.UUID(str(raw_user_id))
    except ValueError as exc:
      raise RuntimeError("SectionBuilder received invalid user_id metadata.") from exc

    # Resolve runtime configuration to determine the monthly section quota limit.
    session_factory = get_session_factory()
    if session_factory is None:
      raise RuntimeError("Database session factory unavailable for quota reservation.")
    async with session_factory() as session:
      # Resolve the user and tier so runtime config can be enforced.
      user = await get_user_by_id(session, reservation_user_id)
      if user is None:
        raise RuntimeError("SectionBuilder quota reservation failed: user not found.")
      tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
      # Require settings in metadata so runtime config resolution remains deterministic.
      settings = (ctx.metadata or {}).get("settings")
      if settings is None:
        raise RuntimeError("SectionBuilder missing settings metadata for quota resolution.")
      runtime_config = await resolve_effective_runtime_config(session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
      reservation_limit = int(runtime_config.get("limits.sections_per_month") or 0)
      if reservation_limit <= 0:
        raise QuotaExceededError("section.generate quota disabled")

    try:
      # Reserve monthly section quota before running the section builder.
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        section_metadata = {"job_id": str(ctx.job_id), "section_index": int(input_data.section_number)}
        await reserve_quota(
          session, user_id=reservation_user_id, metric_key="section.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(input_data.section_number), metadata=section_metadata
        )
      reservation_active = True

      # Prefer deterministic fixture output during local/test runs.
      dummy_json = self._load_dummy_json()

      if dummy_json is not None:
        section_index = input_data.section_number
        topic = request.topic
        validator = self._schema_service.validate_section_payload
        ok, errors, _ = validator(dummy_json, topic=topic, section_index=section_index)
        validation_errors = [] if ok else errors
        # Commit quota reservation once section generation succeeds.
        async with session_factory() as session:
          # Build quota metadata for audit logging.
          commit_metadata = {"job_id": str(ctx.job_id), "section_index": int(input_data.section_number)}
          await commit_quota_reservation(
            session, user_id=reservation_user_id, metric_key="section.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(input_data.section_number), metadata=commit_metadata
          )
        return StructuredSection(section_number=section_index, payload=dummy_json, validation_errors=validation_errors)

      schema_version = str((ctx.metadata or {}).get("schema_version", ""))
      structured_output = bool((ctx.metadata or {}).get("structured_output", True))
      prompt_text = render_section_builder_prompt(request, input_data, schema_version)
      if request.widgets:
        allowed_widgets = request.widgets
      elif request.blueprint:
        from app.schema.widget_preference import get_widget_preference

        allowed_widgets = get_widget_preference(request.blueprint, request.teaching_style)
      else:
        allowed_widgets = None

      if allowed_widgets:
        schema = self._schema_service.subset_section_schema(allowed_widgets)
      else:
        schema = self._schema_service.section_schema()
      purpose = f"build_section_{input_data.section_number}_of_{request.depth}"
      call_index = f"{input_data.section_number}/{request.depth}"

      # Apply context to correlate provider calls with the agent and lesson topic.
      with llm_call_context(agent=self.name, lesson_topic=request.topic, job_id=ctx.job_id, purpose=purpose, call_index=call_index):
        if structured_output:
          schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
          try:
            response = await self._model.generate_structured(prompt_text, schema)
          except Exception as exc:  # noqa: BLE001
            if not is_output_error(exc):
              raise
            # Retry the same request with the parser error appended.
            retry_prompt = self._build_json_retry_prompt(prompt_text=prompt_text, error=exc)
            retry_purpose = f"build_section_retry_{input_data.section_number}_of_{request.depth}"
            retry_call_index = f"retry/{input_data.section_number}/{request.depth}"

            with llm_call_context(agent=self.name, lesson_topic=request.topic, job_id=ctx.job_id, purpose=retry_purpose, call_index=retry_call_index):
              response = await self._model.generate_structured(retry_prompt, schema)

            self._record_usage(agent=self.name, purpose=retry_purpose, call_index=retry_call_index, usage=response.usage)

          self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=response.usage)
          section_json = response.content
        else:
          raise RuntimeError("Structured output is required for section builder generation.")

      section_index = input_data.section_number
      topic = request.topic

      # Validate the structured section against the schema.
      validator = self._schema_service.validate_section_payload
      ok, errors, _ = validator(section_json, topic=topic, section_index=section_index)
      validation_errors = [] if ok else errors
      # Commit quota reservation once section generation succeeds.
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        commit_metadata = {"job_id": str(ctx.job_id), "section_index": int(input_data.section_number)}
        await commit_quota_reservation(
          session, user_id=reservation_user_id, metric_key="section.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(input_data.section_number), metadata=commit_metadata
        )
      return StructuredSection(section_number=section_index, payload=section_json, validation_errors=validation_errors)
    except Exception:  # noqa: BLE001
      # Release quota reservation when section builder fails.
      logger.error("SectionBuilder failed during execution.", exc_info=True)
      if reservation_active and reservation_user_id is not None:
        try:
          async with session_factory() as session:
            # Build quota metadata for audit logging.
            release_metadata = {"job_id": str(ctx.job_id), "section_index": int(input_data.section_number), "reason": "section_builder_failed"}
            await release_quota_reservation(
              session, user_id=reservation_user_id, metric_key="section.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(input_data.section_number), metadata=release_metadata
            )
        except Exception:  # noqa: BLE001
          logger.error("SectionBuilder failed to release section quota reservation.", exc_info=True)
      raise
