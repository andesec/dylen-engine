"""OpenRouter provider stubs."""

from __future__ import annotations

import re
from typing import Any, Final

from app.ai.providers.base import AIModel, ModelResponse, Provider, SimpleModelResponse


class OpenRouterModel(AIModel):
    """Stubbed OpenRouter model client."""

    def __init__(self, name: str) -> None:
        self.name: str = name
        self.supports_structured_output = True

    async def generate(self, prompt: str) -> ModelResponse:
        """Return placeholder content until OpenRouter SDK is integrated."""
        return SimpleModelResponse(
            content=f"[OpenRouter:{self.name}] Placeholder response to: {prompt}"
        )

    async def generate_structured(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Return a deterministic lesson skeleton that matches the schema."""
        topic = _extract_topic(prompt) or "Lesson"
        return _build_lesson_payload(topic)


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


def _extract_topic(prompt: str) -> str | None:
    match = re.search(r"Topic:\s*(.+)", prompt)
    if match:
        return match.group(1).strip()
    return None


def _build_lesson_payload(topic: str) -> dict[str, Any]:
    return {
        "title": topic,
        "blocks": [
            {
                "section": "Overview",
                "items": [
                    f"Welcome to {topic}.",
                    {"tip": "Start by defining the key terms."},
                ],
            },
            {
                "section": "Practice",
                "items": [
                    {"ul": [f"Identify a core concept in {topic}.", "Sketch a simple example."]},
                    {"flip": [f"What is {topic}?", "A concise definition goes here."]},
                ],
            },
        ],
    }
