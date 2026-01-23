"""Routing utilities for provider/model selection."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, Any

from app.ai.errors import is_provider_error
from app.ai.providers.audit import instrument_model
from app.ai.providers.base import AIModel, ModelResponse, Provider, StructuredModelResponse
from app.schema.lesson_catalog import _GATHERER_MODELS, _PLANNER_MODELS, _REPAIRER_MODELS, _STRUCTURER_MODELS

if TYPE_CHECKING:
  pass


class ProviderMode(str, Enum):
  """Supported provider modes."""

  GEMINI = "gemini"
  OPENROUTER = "openrouter"
  VERTEXAI = "vertexai"


def get_provider_for_mode(mode: str | ProviderMode) -> Provider:
  """Return a provider instance for the given mode."""
  key = mode.value if isinstance(mode, ProviderMode) else mode
  if key == ProviderMode.GEMINI.value:
    from app.ai.providers.gemini import GeminiProvider

    return GeminiProvider()
  if key == ProviderMode.OPENROUTER.value:
    from app.ai.providers.openrouter import OpenRouterProvider

    return OpenRouterProvider()
  if key == ProviderMode.VERTEXAI.value:
    from app.ai.providers.vertex_ai import VertexAIProvider

    return VertexAIProvider()
  raise ValueError(f"Unsupported provider mode '{mode}'.")


def get_model_for_mode(mode: str | ProviderMode, model: str | None = None, *, agent: str | None = None) -> AIModel:
  """Return a model client for the given mode and model name."""
  provider = get_provider_for_mode(mode)
  provider_name = getattr(provider, "name", mode.value if isinstance(mode, ProviderMode) else str(mode))
  model_sequence = _build_model_sequence(provider=provider, model=model, agent=agent)
  return FallbackModel(provider=provider, provider_name=provider_name, model_sequence=model_sequence)


def _build_model_sequence(provider: Provider, model: str | None, agent: str | None) -> list[str]:
  """Build a fallback list of models to try for a provider."""
  # Prefer the requested model, then the agent order, then provider defaults for fallback coverage.
  available = list(getattr(provider, "_AVAILABLE_MODELS", []))
  default_model = getattr(provider, "_DEFAULT_MODEL", None)
  sequence: list[str] = []
  agent_models = _ordered_agent_models(agent, available)

  if model:
    sequence.append(model)

  if agent_models:
    # Rotate the agent list so retries walk the next model in order.
    ordered = _rotate_models(agent_models, model) if model else agent_models

    for name in ordered:
      if name not in sequence:
        sequence.append(name)

  if default_model and default_model not in sequence:
    sequence.append(default_model)

  for name in sorted(available):
    if name not in sequence:
      sequence.append(name)

  return sequence


def _ordered_agent_models(agent: str | None, available: list[str]) -> list[str]:
  """Return agent-specific model ordering filtered by provider availability."""

  if not agent:
    return []

  # Filter the per-agent list to keep only models the provider can serve.
  key = agent.lower()
  ordered = _AGENT_MODEL_ORDER.get(key, [])
  return [name for name in ordered if name in available]


def _rotate_models(models: list[str], start: str | None) -> list[str]:
  """Rotate a list so the requested model is first, preserving order."""

  if not start or start not in models:
    return list(models)

  # Place the requested model first while preserving relative order for fallbacks.
  start_index = models.index(start)
  return models[start_index:] + models[:start_index]


_AGENT_MODEL_ORDER: dict[str, list[str]] = {"gatherer": _GATHERER_MODELS, "gatherer_structurer": _GATHERER_MODELS, "planner": _PLANNER_MODELS, "structurer": _STRUCTURER_MODELS, "repairer": _REPAIRER_MODELS}


class FallbackModel(AIModel):
  """Model wrapper that retries with fallback models on provider errors."""

  def __init__(self, *, provider: Provider, provider_name: str, model_sequence: list[str]) -> None:
    self._provider = provider
    self._provider_name = provider_name
    self._model_sequence = model_sequence
    self._active_index = -1
    self._active_model: AIModel | None = None
    # Prime the first available model before serving requests.
    self._activate_next_model()

  async def generate(self, prompt: str) -> ModelResponse:
    """Generate text while falling back on provider/model errors."""
    return await self._attempt(lambda model: model.generate(prompt))

  async def generate_structured(self, prompt: str, schema: dict[str, Any]) -> StructuredModelResponse:
    """Generate structured output while falling back on provider/model errors."""
    return await self._attempt(lambda model: model.generate_structured(prompt, schema))

  async def _attempt(self, func: Callable[[AIModel], Any]) -> Any:
    """Execute a model call with provider-aware fallbacks."""
    while True:
      model = self._active_model

      if model is None:
        raise RuntimeError("No model available for provider fallback.")

      try:
        return await func(model)
      except Exception as exc:  # noqa: BLE001
        if not is_provider_error(exc):
          raise

        if not self._activate_next_model():
          raise

  def _activate_next_model(self) -> bool:
    """Activate the next available model in the fallback sequence."""
    next_index = self._active_index + 1
    while next_index < len(self._model_sequence):
      model_name = self._model_sequence[next_index]
      try:
        model_client = self._provider.get_model(model_name)
      except Exception as exc:  # noqa: BLE001
        if not is_provider_error(exc):
          raise
        next_index += 1
        continue

      # Wrap provider models to capture audit telemetry without changing call sites.
      self._active_model = instrument_model(model_client, self._provider_name)
      self.name = getattr(self._active_model, "name", model_name)
      self.supports_structured_output = getattr(self._active_model, "supports_structured_output", False)
      self._active_index = next_index
      return True

    return False
