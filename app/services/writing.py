"""Service for writing task evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.ai.agents.prompts import _load_prompt
from app.ai.router import get_model_for_mode
from app.ai.utils.cost import calculate_total_cost
from app.schema.lessons import FreeText, InputLine, Lesson, Section, Subsection, SubsectionWidget, SubsectionWidgetType
from app.services.llm_pricing import load_pricing_table
from app.telemetry.context import llm_call_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class WritingCheckResult:
  """Output from the writing check service."""

  ok: bool
  issues: list[str]
  feedback: str
  logs: list[str]
  usage: list[dict[str, Any]]
  total_cost: float


class WritingCheckService:
  """Evaluates user text against criteria using AI."""

  def __init__(self, *, provider: str, model: str | None) -> None:
    self._provider = provider
    self._model_name = model

  async def check_response(self, *, session: AsyncSession, text: str, requester_user_id: str, widget_id: str | None = None, criteria: dict[str, Any] | None = None, runtime_config: dict[str, Any] | None = None) -> WritingCheckResult:
    ai_prompt = None
    wordlist = None

    if widget_id:
      mapping_result = await session.execute(
        select(SubsectionWidget.widget_type, SubsectionWidget.widget_id)
        .join(Subsection, Subsection.id == SubsectionWidget.subsection_id)
        .join(Section, Section.section_id == Subsection.section_id)
        .join(Lesson, Lesson.lesson_id == Section.lesson_id)
        .where(SubsectionWidget.public_id == widget_id, SubsectionWidget.is_archived.is_(False), Subsection.is_archived.is_(False), Lesson.user_id == requester_user_id, Lesson.is_archived.is_(False))
        .limit(1)
      )
      mapping = mapping_result.first()
      if mapping is None or mapping.widget_id is None:
        return WritingCheckResult(ok=False, issues=["Widget not found"], feedback="The checking criteria could not be found.", logs=[f"Widget {widget_id} not found"], usage=[], total_cost=0.0)
      try:
        underlying_id = int(mapping.widget_id)
      except ValueError:
        return WritingCheckResult(ok=False, issues=["Widget not found"], feedback="The checking criteria could not be found.", logs=[f"Widget {widget_id} not found"], usage=[], total_cost=0.0)

      widget_type = mapping.widget_type

      if widget_type == SubsectionWidgetType.INPUTLINE:
        input_line_result = await session.execute(select(InputLine.ai_prompt, InputLine.wordlist).where(InputLine.id == underlying_id))
        input_line_row = input_line_result.first()
        if input_line_row:
          ai_prompt = input_line_row.ai_prompt
          wordlist = input_line_row.wordlist
      elif widget_type == SubsectionWidgetType.FREETEXT:
        free_text_result = await session.execute(select(FreeText.ai_prompt, FreeText.wordlist).where(FreeText.id == underlying_id))
        free_text_row = free_text_result.first()
        if free_text_row:
          ai_prompt = free_text_row.ai_prompt
          wordlist = free_text_row.wordlist
      else:
        return WritingCheckResult(
          ok=False,
          issues=["Widget not supported"],
          feedback="This widget type is not supported for writing checks.",
          logs=[f"Unsupported writing widget type: {widget_type.value if widget_type else 'None'} for widget {widget_id}"],
          usage=[],
          total_cost=0.0,
        )

      if not ai_prompt:
        return WritingCheckResult(ok=False, issues=["Widget not found"], feedback="The checking criteria could not be found.", logs=[f"Widget {widget_id} not found"], usage=[], total_cost=0.0)
    elif criteria:
      # Legacy fallback
      ai_prompt = json.dumps(criteria, indent=2)
    else:
      return WritingCheckResult(ok=False, issues=["Invalid Request"], feedback="No criteria provided.", logs=["Missing criteria or widget_id"], usage=[], total_cost=0.0)

    model = get_model_for_mode(self._provider, self._model_name)

    prompt = self._render_prompt(text, ai_prompt, wordlist)

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

      # Load active pricing data for cost estimates.
      pricing_table = await load_pricing_table(session)
      total_cost = calculate_total_cost(usage, pricing_table, provider=self._provider)

      return WritingCheckResult(ok=content.get("ok", False), issues=content.get("issues", []), feedback=content.get("feedback", ""), logs=[f"Writing check completed with status: {content.get('ok')}"], usage=usage, total_cost=total_cost)
    except Exception as e:
      return WritingCheckResult(ok=False, issues=[f"Evaluation error: {str(e)}"], feedback="We encountered an error while evaluating your response.", logs=[f"Error during writing check: {str(e)}"], usage=[], total_cost=0.0)

  def _render_prompt(self, text: str, ai_prompt: str, wordlist: str | None = None) -> str:
    template = _load_prompt("writing_check.md")
    wordlist_block = ""
    if wordlist:
      wordlist_block = f"\nWORDLIST (Optional terms to usage):\n{wordlist}\n"
    rendered = template
    rendered = rendered.replace("{{AI_PROMPT}}", ai_prompt)
    rendered = rendered.replace("{{WORDLIST_BLOCK}}", wordlist_block)
    rendered = rendered.replace("{{USER_TEXT}}", text)
    return rendered
