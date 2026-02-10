from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.ai.agents.base import BaseAgent
from app.ai.pipeline.contracts import JobContext
from app.core.database import get_session_factory
from app.schema.quotas import QuotaPeriod
from app.schema.tutor import TutorAudio
from app.services.quota_buckets import QuotaExceededError, commit_quota_reservation, release_quota_reservation, reserve_quota
from app.services.runtime_config import resolve_effective_runtime_config
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.telemetry.context import llm_call_context

logger = logging.getLogger(__name__)


class TutorAgent(BaseAgent[dict[str, Any], list[int]]):
  """Generates audio coaching for a lesson section."""

  name = "TutorAgent"

  async def run(self, input_data: dict[str, Any], ctx: JobContext) -> list[int]:
    """Generate speech audio segments for each subsection and persist them."""
    logger = logging.getLogger(__name__)
    section_index = input_data["section_index"]
    topic = input_data["topic"]
    section_data = input_data["section_data"]
    learning_points = input_data.get("learning_data_points", [])

    subsections = section_data.get("subsections", [])
    audio_ids = []
    reservation_limit = 0
    reservation_active = False
    reservation_user_id: uuid.UUID | None = None
    # Require a database session factory for quota reservation and persistence.
    session_factory = get_session_factory()
    if not session_factory:
      raise RuntimeError("Database session factory unavailable for quota reservation.")

    # Resolve the user id for quota reservations.
    raw_user_id = (ctx.metadata or {}).get("user_id")
    if not raw_user_id:
      raise RuntimeError("Tutor missing user_id metadata for quota reservation.")
    try:
      reservation_user_id = uuid.UUID(str(raw_user_id))
    except ValueError as exc:
      raise RuntimeError("Tutor received invalid user_id metadata.") from exc

    # Resolve runtime configuration for the tutor quota limit.
    async with session_factory() as session:
      user = await get_user_by_id(session, reservation_user_id)
      if user is None:
        raise RuntimeError("Tutor quota reservation failed: user not found.")
      tier_id, _tier_name = await get_user_subscription_tier(session, user.id)
      settings = (ctx.metadata or {}).get("settings")
      if settings is None:
        raise RuntimeError("Tutor missing settings metadata for quota resolution.")
      runtime_config = await resolve_effective_runtime_config(session, settings=settings, org_id=user.org_id, subscription_tier_id=tier_id, user_id=None)
      reservation_limit = int(runtime_config.get("limits.tutor_sections_per_month") or 0)
      if reservation_limit <= 0:
        raise QuotaExceededError("tutor.generate quota disabled")

    try:
      # Reserve monthly tutor quota before generating audio.
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        reserve_metadata = {"job_id": str(ctx.job_id), "section_index": int(section_index)}
        await reserve_quota(session, user_id=reservation_user_id, metric_key="tutor.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(section_index), metadata=reserve_metadata)
      reservation_active = True
      # Generate scripts and audio outside DB transactions to avoid holding locks during LLM calls.
      generated_segments: list[tuple[int, str, bytes]] = []
      for idx, subsection in enumerate(subsections):
        subsection_title = subsection.get("subsection") or subsection.get("section") or f"Subsection {idx + 1}"
        script_prompt = self._build_script_prompt(topic, learning_points, subsection_title, subsection)
        purpose = f"tutor_script_{section_index}_{idx}"
        call_index = f"{section_index}/{idx}"
        with llm_call_context(agent=self.name, lesson_topic=topic, job_id=ctx.job_id, purpose=purpose, call_index=call_index):
          response = await self._model.generate(script_prompt)
          self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=response.usage)
        script = response.content.strip()
        try:
          audio_bytes = await self._model.generate_speech(script)
        except NotImplementedError:
          logger.warning("Model %s does not support speech generation.", self._model.name)
          continue
        except Exception as exc:
          logger.error("Failed to generate speech for %s: %s", purpose, exc)
          continue
        generated_segments.append((idx, script, audio_bytes))
      # Persist audio rows in a short-lived transaction after generation completes.
      async with session_factory() as session:
        for idx, script, audio_bytes in generated_segments:
          audio_entry = TutorAudio(job_id=ctx.job_id, section_number=section_index, subsection_index=idx, text_content=script, audio_data=audio_bytes)
          session.add(audio_entry)
          await session.flush()
          audio_ids.append(audio_entry.id)
        await session.commit()

      # Commit the reservation once audio generation is complete.
      async with session_factory() as session:
        # Build quota metadata for audit logging.
        commit_metadata = {"job_id": str(ctx.job_id), "section_index": int(section_index)}
        await commit_quota_reservation(session, user_id=reservation_user_id, metric_key="tutor.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(section_index), metadata=commit_metadata)
      return audio_ids
    except Exception:  # noqa: BLE001
      # Release quota reservation when tutor generation fails.
      logger.error("Tutor failed during execution.", exc_info=True)
      if reservation_active and reservation_user_id is not None:
        try:
          async with session_factory() as session:
            # Build quota metadata for audit logging.
            release_metadata = {"job_id": str(ctx.job_id), "section_index": int(section_index), "reason": "tutor_failed"}
            await release_quota_reservation(
              session, user_id=reservation_user_id, metric_key="tutor.generate", period=QuotaPeriod.MONTH, quantity=1, limit=reservation_limit, job_id=str(ctx.job_id), section_index=int(section_index), metadata=release_metadata
            )
        except Exception:  # noqa: BLE001
          logger.error("Tutor failed to release tutor quota reservation.", exc_info=True)
      raise

  def _build_script_prompt(self, topic: str, points: list[str], sub_title: str, subsection: dict[str, Any]) -> str:
    """Construct a prompt for generating a subsection coaching script."""
    points_str = "\n".join(f"- {p}" for p in points) or "- (none provided)"
    content_str = json.dumps(subsection, indent=2, default=str)

    return f"""
You are an expert educational tutor.
Topic: {topic}
Subsection: {sub_title}

Key Learning Points:
{points_str}

Content:
{content_str}

Write a short, engaging, and encouraging audio script (spoken text) for this subsection.
The script should reinforce the key learning points and guide the learner through the content.
Keep it concise (under 1 minute spoken).
Do not include "Script:" or other metadata labels, just the spoken text.
"""
