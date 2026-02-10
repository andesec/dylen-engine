"""Audit wrapper for AI model calls."""

from __future__ import annotations

import sys
import time
from typing import Any, cast

from app.ai.providers.base import AIModel, ModelResponse, StructuredModelResponse
from app.telemetry.llm_audit import finalize_llm_call, serialize_request, serialize_response, start_llm_call, utc_now


class AuditModel(AIModel):
  """Wrap an AI model so every call is captured for audit storage."""

  def __init__(self, model: AIModel, provider_name: str) -> None:
    self._model = model
    self._provider_name = provider_name
    self.name = getattr(model, "name", "unknown")
    self.supports_structured_output = getattr(model, "supports_structured_output", False)
    self.last_usage: dict[str, int] | None = None

  async def generate(self, prompt: str) -> ModelResponse:
    """Generate a response while capturing an audit trail."""
    return cast(ModelResponse, await self._capture(prompt=prompt, schema=None))

  async def generate_structured(self, prompt: str, schema: dict[str, Any]) -> StructuredModelResponse:
    """Generate a structured response while capturing an audit trail."""
    return cast(StructuredModelResponse, await self._capture(prompt=prompt, schema=schema))

  async def generate_image(self, prompt: str) -> bytes:
    """Generate image bytes while capturing an audit trail."""
    return cast(bytes, await self._capture(prompt=prompt, schema=None, call_mode="generate_image"))

  async def _capture(self, *, prompt: str, schema: dict[str, Any] | None, call_mode: str | None = None) -> ModelResponse | bytes:
    """Call the underlying model while capturing audit metadata."""
    started_at = utc_now()
    start_time = time.monotonic()
    response: Any = None
    usage: dict[str, int] | None = None
    # Serialize prompt + schema so the request can be stored before any network call.
    request_payload = serialize_request(prompt, schema)
    request_type = call_mode or ("generate_structured" if schema is not None else "generate")
    # Insert the pending call record so failures are still tracked.
    call_id = await start_llm_call(provider=self._provider_name, model=self.name, request_type=request_type, request_payload=request_payload, started_at=started_at)

    # Capture timing and usage even when the provider raises.

    try:
      # Reset usage before each call so image calls do not leak prior usage metadata.
      self._model.last_usage = None
      if request_type == "generate_image":
        response = await self._model.generate_image(prompt)
      elif schema is None:
        response = await self._model.generate(prompt)

      else:
        response = await self._model.generate_structured(prompt, schema)
      usage = _resolve_usage(response=response, model=self._model)
      self.last_usage = usage

      return response

    finally:
      # Always update the audit row, even when downstream parsing fails.
      duration_ms = int((time.monotonic() - start_time) * 1000)
      error = cast(BaseException | None, sys.exc_info()[1])
      if isinstance(response, (bytes, bytearray)):
        content: Any = f"<binary:{len(response)} bytes>"
      else:
        content = getattr(response, "content", None) if response is not None else response
      response_payload = serialize_response(content)
      await finalize_llm_call(call_id=call_id, response_payload=response_payload, usage=usage, duration_ms=duration_ms, error=error)


def _resolve_usage(*, response: Any, model: AIModel) -> dict[str, int] | None:
  """Resolve usage from typed responses first, then provider side-channel usage."""
  direct_usage = getattr(response, "usage", None) if response is not None else None
  if isinstance(direct_usage, dict):
    return direct_usage
  model_usage = getattr(model, "last_usage", None)
  if isinstance(model_usage, dict):
    return model_usage
  return None


def instrument_model(model: AIModel, provider_name: str) -> AIModel:
  """Wrap a model with audit logging while preserving the original interface."""
  return AuditModel(model, provider_name)
