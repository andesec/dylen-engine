"""Fenster Builder agent implementation."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import _load_prompt
from app.ai.pipeline.contracts import JobContext
from app.core.database import get_session_factory
from app.schema.quotas import QuotaPeriod
from app.services.quota_buckets import QuotaExceededError, commit_quota_reservation, release_quota_reservation, reserve_quota
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.users import get_user_by_id, get_user_subscription_tier

logger = logging.getLogger(__name__)


class FensterBuilderAgent(BaseAgent[dict[str, Any], str]):
  """Generate interactive widget HTML."""

  name = "FensterBuilder"

  async def run(self, input_data: dict[str, Any], ctx: JobContext) -> str:
    """Generate the widget HTML."""
    reservation_limit = 0
    reservation_active = False
    reservation_user_id: uuid.UUID | None = None
    # Require a database session factory for quota reservation and persistence.
    session_factory = get_session_factory()
    if session_factory is None:
      raise RuntimeError("Database session factory unavailable for quota reservation.")

    # Resolve the user id for quota reservations.
    raw_user_id = (ctx.metadata or {}).get("user_id")
    if not raw_user_id:
      raise RuntimeError("FensterBuilder missing user_id metadata for quota reservation.")
    try:
      reservation_user_id = uuid.UUID(str(raw_user_id))
    except ValueError as exc:
      raise RuntimeError("FensterBuilder received invalid user_id metadata.") from exc

    # Resolve runtime configuration for the widget quota limit.
    async with session_factory() as session:
      user = await get_user_by_id(session, reservation_user_id)
      if user is None:
        raise RuntimeError("FensterBuilder quota reservation failed: user not found.")
      tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
      settings = (ctx.metadata or {}).get("settings")
      if settings is None:
        raise RuntimeError("FensterBuilder missing settings metadata for quota resolution.")
      runtime_config = await resolve_effective_runtime_config(session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
      reservation_limit = int(runtime_config.get("limits.fenster_widgets_per_month") or 0)
      if reservation_limit <= 0:
        raise QuotaExceededError("fenster.widget.generate quota disabled")

    try:
      # Reserve monthly widget quota before generating HTML.
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        reserve_metadata = {"job_id": str(ctx.job_id)}
        await reserve_quota(session, user_id=reservation_user_id, metric_key="fenster.widget.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), metadata=reserve_metadata)
      reservation_active = True
      # Load the prompt template for widget generation.
      prompt_template = _load_prompt("fenster_builder.md")
      # Serialize technical constraints to keep the prompt stable.
      constraints = input_data.get("technical_constraints")
      constraints_str = str(constraints) if constraints else "None"
      # Replace prompt tokens with request values.
      tokens = {"{{concept_context}}": input_data.get("concept_context", ""), "{{target_audience}}": input_data.get("target_audience", ""), "{{technical_constraints}}": constraints_str}
      prompt_text = prompt_template
      for k, v in tokens.items():
        prompt_text = prompt_text.replace(k, v)
      # Generate widget HTML from the model.
      response = await self._model.generate(prompt_text)
      self._record_usage(agent=self.name, purpose="build_widget", call_index="1/1", usage=response.usage)
      content = response.content.strip()
      # Remove markdown fences to ensure clean HTML output.
      if content.startswith("```html"):
        content = content[7:]
      elif content.startswith("```"):
        content = content[3:]
      if content.endswith("```"):
        content = content[:-3]
      # Commit the reservation once widget generation succeeds.
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        commit_metadata = {"job_id": str(ctx.job_id)}
        await commit_quota_reservation(session, user_id=reservation_user_id, metric_key="fenster.widget.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), metadata=commit_metadata)
      return content.strip()
    except Exception:  # noqa: BLE001
      # Release quota reservation when widget generation fails.
      logger.error("FensterBuilder failed during execution.", exc_info=True)
      if reservation_active and reservation_user_id is not None:
        try:
          async with session_factory() as session:
            # Build quota metadata for audit logging.
            release_metadata = {"job_id": str(ctx.job_id), "reason": "fenster_builder_failed"}
            await release_quota_reservation(session, user_id=reservation_user_id, metric_key="fenster.widget.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), metadata=release_metadata)
        except Exception:  # noqa: BLE001
          logger.error("FensterBuilder failed to release widget quota reservation.", exc_info=True)
      raise
