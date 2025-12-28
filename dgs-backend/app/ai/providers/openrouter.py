"""OpenRouter provider stubs."""

from __future__ import annotations

from typing import Final

from app.ai.providers.base import AIModel, ModelResponse, Provider, SimpleModelResponse


class OpenRouterModel(AIModel):
    """Stubbed OpenRouter model client."""

    def __init__(self, name: str) -> None:
        self.name: str = name

    async def generate(self, prompt: str) -> ModelResponse:
        """Return placeholder content until OpenRouter SDK is integrated."""
        return SimpleModelResponse(
            content=f"[OpenRouter:{self.name}] Placeholder response to: {prompt}"
        )


class OpenRouterProvider(Provider):
    """Stubbed OpenRouter provider."""

    _DEFAULT_MODEL: Final[str] = "openrouter/gpt-4.1"
    _AVAILABLE_MODELS: Final[set[str]] = {_DEFAULT_MODEL, "openrouter/claude-3-opus"}

    def __init__(self) -> None:
        self.name: str = "openrouter"

    def get_model(self, model: str | None = None) -> AIModel:
        """Return a stubbed OpenRouter model client."""
        model_name = model or self._DEFAULT_MODEL
        if model_name not in self._AVAILABLE_MODELS:
            raise ValueError(f"Unsupported OpenRouter model '{model_name}'.")
        return OpenRouterModel(model_name)
