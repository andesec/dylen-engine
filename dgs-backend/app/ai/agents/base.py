"""Base class for AI agents."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Generic, TypeVar, cast

from app.ai.json_parser import parse_json_with_fallback
from app.ai.pipeline.contracts import JobContext
from app.ai.providers.base import AIModel
from app.progress.tracker import ProgressTracker
from app.schema.service import SchemaService

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")
UsageSink = Callable[[dict[str, Any]], None] | None
Progress = ProgressTracker | None
Metrics = dict[str, Any] | None
Model = AIModel
Schema = SchemaService
OptStr = str | None
OptInt = int | None
Usage = UsageSink


class BaseAgent(ABC, Generic[InputT, OutputT]):
  """Base agent with shared dependencies."""

  name: str

  def __init__(self, *, model: Model, prov: str, schema: Schema, prog: Progress = None, use: Usage = None) -> None:
    self._model = model
    self._provider_name = prov
    self._schema_service = schema
    self._progress = prog
    self._usage_sink = use

  @abstractmethod
  async def run(self, input_data: InputT, ctx: JobContext) -> OutputT:
    """Run the agent on input data."""

  def _emit_progress(self, *, p: str, s: OptStr = None, i: OptInt = None, m: OptStr = None, mt: Metrics = None) -> None:
    if self._progress:
      self._progress.emit(phase=p, step=s, section_id=i, message=m, metrics=mt)

  def _record_usage(
    self, *, agent: str, purpose: str, call_index: str, usage: dict[str, int] | None
  ) -> None:
    if not usage or not self._usage_sink:
      return
    payload = {
      "model": getattr(self._model, "name", "unknown"),
      "agent": agent,
      "purpose": purpose,
      "call_index": call_index,
      **usage,
    }
    self._usage_sink(payload)

  def _load_dummy_text(self) -> str | None:
    """Return a deterministic dummy response when enabled for this agent."""
    # Use per-agent environment flags to bypass provider calls in local tests.
    return AIModel.load_dummy_response(self.name.upper())

  def _load_dummy_json(self) -> dict[str, Any] | None:
    """Return a parsed dummy JSON payload when enabled for this agent."""
    dummy = self._load_dummy_text()
    if dummy is None:
      return None
    # Mirror provider parsing to keep dummy responses interchangeable.
    cleaned = self._model.strip_json_fences(dummy)

    # Parse with lenient recovery to keep dummy fixtures tolerant of minor issues.
    try:
      return cast(dict[str, Any], parse_json_with_fallback(cleaned))
    except json.JSONDecodeError as exc:
      raise RuntimeError(f"Failed to parse dummy JSON for {self.name}: {exc}") from exc

  def _build_json_retry_prompt(self, *, prompt_text: str, error: Exception) -> str:
    """Append parser errors to prompts so retries can fix invalid JSON."""
    # Include parser failures so the next attempt avoids repeating the error.
    suffix = "\n\n".join(
      [
        "Previous response could not be parsed as JSON.",
        f"Parser error: {error}",
        "Return ONLY valid JSON and ensure the schema is followed exactly.",
      ]
    )
    return f"{prompt_text}\n\n{suffix}"
