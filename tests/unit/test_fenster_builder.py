from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.agents.fenster_builder import FensterBuilderAgent
from app.ai.pipeline.contracts import GenerationRequest, JobContext


@pytest.mark.anyio
async def test_fenster_builder_run():
  mock_model = MagicMock()
  mock_model.generate = AsyncMock()
  mock_model.generate.return_value.content = "<div>Widget</div>"
  mock_model.generate.return_value.usage = {"input_tokens": 10}

  agent = FensterBuilderAgent(model=mock_model, prov="test", schema=MagicMock())

  input_data = {"concept_context": "Test Context", "target_audience": "Beginner", "technical_constraints": {"max_tokens": 100}}

  # Create a minimal valid request for JobContext
  req = GenerationRequest(topic="test", depth="highlights", section_count=2)

  ctx = JobContext(job_id="123", created_at=datetime.utcnow(), provider="test", model="test", request=req)

  result = await agent.run(input_data, ctx)

  assert result == "<div>Widget</div>"
  mock_model.generate.assert_called_once()
  args, _ = mock_model.generate.call_args
  prompt = args[0]
  assert "Test Context" in prompt
  assert "Beginner" in prompt
