"""Gemini provider stubs."""

from __future__ import annotations

from typing import Final

from app.ai.providers.base import AIModel, ModelResponse, Provider, SimpleModelResponse


class GeminiModel(AIModel):
    """Stubbed Gemini model client."""

    def __init__(self, name: str) -> None:
        self.name: str = name

    async def generate(self, prompt: str) -> ModelResponse:
        """Return placeholder content until Gemini SDK is integrated."""
        return SimpleModelResponse(
            content=f"[Gemini:{self.name}] Placeholder response to: {prompt}"
        )


class GeminiProvider(Provider):
    """Stubbed Gemini provider."""

    _DEFAULT_MODEL: Final[str] = "gemini-pro"
    _AVAILABLE_MODELS: Final[set[str]] = {_DEFAULT_MODEL, "gemini-1.5-pro"}

    def __init__(self) -> None:
        self.name: str = "gemini"

    def get_model(self, model: str | None = None) -> AIModel:
        """Return a stubbed Gemini model client."""
        model_name = model or self._DEFAULT_MODEL
        if model_name not in self._AVAILABLE_MODELS:
            raise ValueError(f"Unsupported Gemini model '{model_name}'.")
        return GeminiModel(model_name)
