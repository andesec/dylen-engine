"""Retry and timeout policy wrapper for AI models."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any, Callable

from app.ai.providers.base import AIModel, ModelResponse, StructuredModelResponse


@dataclass(frozen=True)
class ProviderPolicy:
  """Retry/timeout policy configuration."""

  timeout_seconds: float | None = 60.0
  max_retries: int = 2
  backoff_seconds: float = 1.0
  max_backoff_seconds: float = 8.0

  def backoff_delay(self, attempt: int) -> float:
    """Exponential backoff with jitter."""
    base = min(self.backoff_seconds * (2**attempt), self.max_backoff_seconds)
    return base + random.random() * 0.25


class PolicyModel(AIModel):
  """Wraps an AIModel with retry and timeout policy."""

  def __init__(self, model: AIModel, policy: ProviderPolicy) -> None:
    self._model = model
    self._policy = policy
    self.name = getattr(model, "name", "unknown")
    self.supports_structured_output = getattr(model, "supports_structured_output", False)

  async def generate(self, prompt: str) -> ModelResponse:
    """Generate text with retries and timeouts applied."""
    return await self._execute(lambda: self._model.generate(prompt), "generate")

  async def generate_structured(self, prompt: str, schema: dict[str, Any]) -> StructuredModelResponse:
    """Generate structured output with retries and timeouts applied."""
    return await self._execute(lambda: self._model.generate_structured(prompt, schema), "generate_structured")

  async def _execute(self, func: Callable[[], Any], action: str) -> Any:
    last_error: Exception | None = None
    for attempt in range(self._policy.max_retries + 1):
      try:
        if self._policy.timeout_seconds is None:
          return await func()
        return await asyncio.wait_for(func(), timeout=self._policy.timeout_seconds)
      except Exception as exc:
        last_error = exc
        if attempt >= self._policy.max_retries:
          break
        await asyncio.sleep(self._policy.backoff_delay(attempt))
    raise RuntimeError(f"Policy-wrapped {action} failed for {self.name}: {last_error}") from last_error


def apply_policy(model: AIModel, policy: ProviderPolicy | None) -> AIModel:
  """Apply a policy wrapper to a model if configured."""
  if policy is None:
    return model
  return PolicyModel(model, policy)
