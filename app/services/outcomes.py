"""Service helpers for the Outcomes agent."""

from __future__ import annotations

from datetime import UTC, datetime

from app.ai.agents.outcomes import OutcomesAgent
from app.ai.pipeline.contracts import GenerationRequest, JobContext
from app.ai.router import get_model_for_mode
from app.config import Settings
from app.schema.outcomes import OutcomesAgentInput, OutcomesAgentResponse
from app.schema.service import SchemaService
from app.schema.widget_preference import get_widget_preference


async def generate_lesson_outcomes(request: GenerationRequest, *, settings: Settings, provider: str, model: str | None, job_id: str, section_count: int) -> tuple[OutcomesAgentResponse, str]:
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
    details=request.prompt or "",
    learning_focus=request.learning_focus or "comprehensive",
    teaching_style=request.teaching_style or ["adaptive"],
    learner_level=request.learner_level or "student",
    section_count=section_count,
    lesson_language=request.lesson_language or "English",
    secondary_language=request.secondary_language,
  )
  ctx = JobContext(job_id=job_id, created_at=datetime.now(tz=UTC), provider=str(provider), model=getattr(model_instance, "name", model or "default"), request=request)

  result = await agent.run(input_data, ctx)

  # Add suggested widgets filtered by blueprint and teaching approaches
  if result.ok and result.suggested_blueprint:
    # Normalize blueprint name for lookup (e.g., "knowledge_understanding" -> "Knowledge & Understanding")
    blueprint_name = result.suggested_blueprint
    teaching_styles = request.teaching_style or ["adaptive"]

    # Get filtered widgets based on blueprint and teaching approaches
    filtered_widgets = get_widget_preference(blueprint_name, teaching_styles)

    if filtered_widgets:
      # Normalize widget names to match UI expectations (lowercase, no special chars)
      normalized_widgets = ["".join(ch for ch in widget.lower() if ch.isalnum()) for widget in filtered_widgets if widget.lower() != "markdown"]
      result.suggested_widgets = normalized_widgets
    else:
      # If no preference found, provide a default set
      result.suggested_widgets = []

  return (result, getattr(model_instance, "name", model or "default"))
