"""Service helpers for the Outcomes agent."""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai.agents.outcomes import OutcomesAgent
from app.ai.pipeline.contracts import GenerationRequest, JobContext
from app.ai.router import get_model_for_mode
from app.config import Settings
from app.schema.outcomes import OutcomesAgentInput, OutcomesAgentResponse
from app.schema.service import SchemaService


async def generate_lesson_outcomes(request: GenerationRequest, *, settings: Settings, provider: str, model: str | None, job_id: str, max_outcomes: int) -> tuple[OutcomesAgentResponse, str]:
  """Generate a small list of outcomes for a lesson topic.

  How/Why:
    - The endpoint needs a synchronous "preflight" call that checks topic safety and suggests learning outcomes.
    - Provider/model are resolved outside this function to keep routing policy in one place.
  """
  schema = SchemaService()
  # Use the outcomes agent model ordering to keep this agent independent.
  model_instance = get_model_for_mode(provider, model, agent="outcomes")
  agent = OutcomesAgent(model=model_instance, prov=provider, schema=schema)

  input_data = OutcomesAgentInput(
    topic=request.topic,
    details=request.prompt,
    blueprint=request.blueprint,
    teaching_style=request.teaching_style,
    learner_level=request.learner_level,
    depth=request.depth,
    primary_language=request.language,
    widgets=request.widgets,
    max_outcomes=int(max_outcomes),
  )
  ctx = JobContext(job_id=job_id, created_at=datetime.now(tz=UTC), provider=str(provider), model=getattr(model_instance, "name", model or "default"), request=request)

  result = await agent.run(input_data, ctx)
  return (result, getattr(model_instance, "name", model or "default"))
