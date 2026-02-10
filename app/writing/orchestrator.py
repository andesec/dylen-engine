"""Orchestration for writing task evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai.router import get_model_for_mode
from app.schema.lessons import SubjectiveInputWidget
from app.telemetry.context import llm_call_context
from sqlalchemy import select


@dataclass(frozen=True)
class WritingCheckResult:
  """Output from the writing check orchestration."""

  ok: bool
  issues: list[str]
  feedback: str
  logs: list[str]
  usage: list[dict[str, Any]]
  total_cost: float


class WritingCheckOrchestrator:
  """Evaluates user text against criteria using AI."""

  def __init__(self, *, provider: str, model: str | None, session_factory: Any) -> None:
    self._provider = provider
    self._model_name = model
    self._session_factory = session_factory

  async def check_response(self, *, text: str, widget_id: int) -> WritingCheckResult:
    async with self._session_factory() as session:
      result = await session.execute(select(SubjectiveInputWidget.ai_prompt).where(SubjectiveInputWidget.id == widget_id))
      ai_prompt = result.scalar_one_or_none()

    if not ai_prompt:
      return WritingCheckResult(ok=False, issues=["Widget not found"], feedback="The checking criteria could not be found.", logs=[f"Widget {widget_id} not found"], usage=[], total_cost=0.0)

    model = get_model_for_mode(self._provider, self._model_name)

    prompt = self._render_prompt(text, ai_prompt)

    # We always use structured output for JSON agents.
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}}, "feedback": {"type": "string"}}, "required": ["ok", "issues", "feedback"]}

    # Wrap provider calls to capture audit context while preserving fallback flow.
    try:
      # Stamp the provider call with a writing-check context for audit logging.
      with llm_call_context(agent="WritingCheck", lesson_topic=None, job_id=None, purpose="writing_check", call_index="1/1"):
        res = await model.generate_structured(prompt, schema)

      usage = []

      if res.usage:
        usage.append({"model": model.name, "purpose": "check", **res.usage})

      content = res.content

      total_cost = self._calculate_total_cost(usage)

      return WritingCheckResult(ok=content.get("ok", False), issues=content.get("issues", []), feedback=content.get("feedback", ""), logs=[f"Writing check completed with status: {content.get('ok')}"], usage=usage, total_cost=total_cost)
    except Exception as e:
      return WritingCheckResult(ok=False, issues=[f"Evaluation error: {str(e)}"], feedback="We encountered an error while evaluating your response.", logs=[f"Error during writing check: {str(e)}"], usage=[], total_cost=0.0)

  def _calculate_total_cost(self, usage: list[dict[str, Any]]) -> float:
    """Estimate total cost based on token usage. Simplified prices."""
    PRICES = {  # noqa: N806
      "openai/gpt-4o-mini": (0.15, 0.60),
      "openai/gpt-4o": (5.0, 15.0),
      "gemini-2.0-flash": (0.075, 0.30),
      "gemini-2.0-flash-exp": (0.075, 0.30),
    }
    total = 0.0

    # Accumulate token costs for each model entry.
    for entry in usage:
      model = entry.get("model", "")
      p_in, p_out = PRICES.get(model, (0.5, 1.5))
      in_tokens = entry.get("prompt_tokens", 0)
      out_tokens = entry.get("completion_tokens", 0)
      total += (in_tokens / 1_000_000) * p_in
      total += (out_tokens / 1_000_000) * p_out

    return total

  def _render_prompt(self, text: str, ai_prompt: str) -> str:
    return f"""
Evaluate the following user response based on the provided instructions.

INSTRUCTIONS:
{ai_prompt}

USER RESPONSE:
{text}

Return a structured evaluation in JSON format:
{{
  "ok": true/false (if the response meets the core criteria),
  "issues": [list of specific problems found],
  "feedback": "constructive feedback for the user"
}}
"""
