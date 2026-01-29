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
    section_index = input_data["section_index"]
    topic = input_data["topic"]
    section_data = input_data["section_data"]
    learning_points = input_data.get("learning_data_points", [])

    # We iterate over subsections to generate audio
    subsections = section_data.get("subsections", [])

    audio_ids = []

    for idx, subsection in enumerate(subsections):
      subsection_title = subsection.get("subsection") or subsection.get("section") or f"Subsection {idx + 1}"

      # 1. Generate Script
      script_prompt = self._build_script_prompt(topic, learning_points, subsection_title, subsection)

      purpose = f"coach_script_{section_index}_{idx}"
      call_index = f"{section_index}/{idx}"

      with llm_call_context(agent=self.name, lesson_topic=topic, job_id=ctx.job_id, purpose=purpose, call_index=call_index):
        response = await self._model.generate(script_prompt)
        self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=response.usage)

      script = response.content.strip()

      # 2. Generate Audio
      try:
        # We assume the model (Gemini/Vertex) supports generate_speech
        audio_bytes = await self._model.generate_speech(script)
      except NotImplementedError:
        logger.warning("Model %s does not support speech generation.", self._model.name)
        continue
      except Exception as exc:
        logger.error("Failed to generate speech for %s: %s", purpose, exc)
        continue

      # 3. Save to DB
      session_factory = get_session_factory()
      if session_factory:
        async with session_factory() as session:
          audio_entry = CoachAudio(job_id=ctx.job_id, section_number=section_index, subsection_index=idx, text_content=script, audio_data=audio_bytes)
          session.add(audio_entry)
          await session.commit()
          await session.refresh(audio_entry)
          audio_ids.append(audio_entry.id)

    return audio_ids

  def _build_script_prompt(self, topic: str, points: list[str], sub_title: str, subsection: dict[str, Any]) -> str:
    points_str = "\n".join(f"- {p}" for p in points)
    # Serialize subsection content for context
    content_str = json.dumps(subsection, indent=2)

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
