"""Tests for Outcomes agent dummy responses."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from app.ai.agents.outcomes import OutcomesAgent
from app.ai.pipeline.contracts import GenerationRequest, JobContext
from app.ai.providers.base import AIModel, SimpleModelResponse, StructuredModelResponse
from app.schema.outcomes import OutcomesAgentInput
from app.schema.service import SchemaService


class _NoopModel(AIModel):
  """Test model that is never called when dummy output is enabled."""

  def __init__(self) -> None:
    self.name = "noop"
    self.supports_structured_output = True

  async def generate(self, _prompt: str) -> SimpleModelResponse:
    raise AssertionError("Model.generate should not be called when dummy output is enabled.")

  async def generate_structured(self, _prompt: str, _schema: dict) -> StructuredModelResponse:
    raise AssertionError("Model.generate_structured should not be called when dummy output is enabled.")


def test_outcomes_agent_uses_dummy_response(monkeypatch: pytest.MonkeyPatch) -> None:
  # Ensure the helper does not attempt to load the repo `.env` during this unit test.
  from app.ai.providers import base

  base._ENV_LOADED = True

  # Enable deterministic output to avoid provider calls.
  monkeypatch.setenv("DYLEN_USE_DUMMY_OUTCOMES_RESPONSE", "1")
  monkeypatch.delenv("DYLEN_DUMMY_OUTCOMES_RESPONSE_PATH", raising=False)

  agent = OutcomesAgent(model=_NoopModel(), prov="noop", schema=SchemaService())

  request = OutcomesAgentInput(
    topic="Intro to Python", details="Cover lists and loops", blueprint="skillbuilding", teaching_style=["practical"], learner_level="Beginner", depth="highlights", primary_language="English", widgets=["markdownText"], max_outcomes=5
  )
  ctx = JobContext(job_id="job_test_outcomes", created_at=datetime.now(tz=UTC), provider="noop", model="noop", request=GenerationRequest(topic="Intro to Python", prompt="Cover lists and loops", depth="highlights", section_count=2))

  result = asyncio.run(agent.run(request, ctx))

  assert result.ok is True
  assert result.error is None
  assert len(result.outcomes) > 0
