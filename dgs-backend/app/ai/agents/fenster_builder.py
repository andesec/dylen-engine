"""Fenster Builder agent implementation."""

from __future__ import annotations

from typing import Any

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import _load_prompt
from app.ai.pipeline.contracts import JobContext


class FensterBuilderAgent(BaseAgent[dict[str, Any], str]):
  """Generate interactive widget HTML."""

  name = "FensterBuilder"

  async def run(self, input_data: dict[str, Any], ctx: JobContext) -> str:
    """Generate the widget HTML."""
    # Load prompt
    prompt_template = _load_prompt("fenster_builder.md")

    # Serialize constraints if present
    constraints = input_data.get("technical_constraints")
    constraints_str = str(constraints) if constraints else "None"

    # Replace tokens
    tokens = {
      "{{concept_context}}": input_data.get("concept_context", ""),
      "{{target_audience}}": input_data.get("target_audience", ""),
      "{{technical_constraints}}": constraints_str,
    }

    prompt_text = prompt_template
    for k, v in tokens.items():
      prompt_text = prompt_text.replace(k, v)

    # Generate
    # Stamp the provider call with agent context for audit logging.
    # Note: We don't have full llm_call_context usage here yet, relying on BaseAgent/Model behavior.
    # But usually we should wrap it if we want audit logs.
    # BaseAgent doesn't wrap automatically.

    response = await self._model.generate(prompt_text)
    self._record_usage(agent=self.name, purpose="build_widget", call_index="1/1", usage=response.usage)

    content = response.content.strip()

    # Remove markdown fences if present (sanity check)
    if content.startswith("```html"):
      content = content[7:]
    elif content.startswith("```"):
      content = content[3:]

    if content.endswith("```"):
      content = content[:-3]

    return content.strip()
