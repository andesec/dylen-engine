from __future__ import annotations

import json
import logging
from typing import Any

from app.ai.agents.base import BaseAgent
from app.ai.pipeline.contracts import JobContext
from app.core.database import get_session_factory
from app.schema.coach import CoachAudio
from app.telemetry.context import llm_call_context

logger = logging.getLogger(__name__)


class CoachAgent(BaseAgent[dict[str, Any], list[int]]):
  """Generates audio coaching for a lesson section."""

  name = "CoachAgent"

  async def run(self, input_data: dict[str, Any], ctx: JobContext) -> list[int]:
    """Generate speech audio segments for each subsection and persist them."""
    section_index = input_data["section_index"]
    topic = input_data["topic"]
    section_data = input_data["section_data"]
    learning_points = input_data.get("learning_data_points", [])

    subsections = section_data.get("subsections", [])
    audio_ids = []
    session_factory = get_session_factory()
    if not session_factory:
      logger.error("Database session factory unavailable; skipping Coach audio persistence.")
      return audio_ids

    async with session_factory() as session:
      for idx, subsection in enumerate(subsections):
        subsection_title = subsection.get("subsection") or subsection.get("section") or f"Subsection {idx + 1}"
        script_prompt = self._build_script_prompt(topic, learning_points, subsection_title, subsection)
        purpose = f"coach_script_{section_index}_{idx}"
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

        audio_entry = CoachAudio(job_id=ctx.job_id, section_number=section_index, subsection_index=idx, text_content=script, audio_data=audio_bytes)
        session.add(audio_entry)
        await session.flush()
        audio_ids.append(audio_entry.id)

      await session.commit()

    return audio_ids

  def _build_script_prompt(self, topic: str, points: list[str], sub_title: str, subsection: dict[str, Any]) -> str:
    """Construct a prompt for generating a subsection coaching script."""
    points_str = "\n".join(f"- {p}" for p in points) or "- (none provided)"
    content_str = json.dumps(subsection, indent=2, default=str)

    return f"""
You are an expert educational coach.
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
