"""OpenRouter provider implementation using openai SDK."""

from __future__ import annotations

import json
import os
from typing import Any, Final, cast

from openai import AsyncOpenAI

from app.ai.providers.base import (
    AIModel,
    ModelResponse,
    Provider,
    SimpleModelResponse,
    StructuredModelResponse,
)


class OpenRouterModel(AIModel):
    """OpenRouter model client with structured output support."""

    def __init__(self, name: str, api_key: str | None = None, base_url: str | None = None) -> None:
        self.name: str = name
        self.supports_structured_output = True

        # Configure OpenRouter client
        api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable is required")

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or "https://openrouter.ai/api/v1",
        )

    async def generate(self, prompt: str) -> ModelResponse:
        """Generate text response from OpenRouter."""
        response = await self._client.chat.completions.create(
            model=self.name,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content or ""
        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        return SimpleModelResponse(content=content, usage=usage)

    async def generate_structured(
        self, prompt: str, schema: dict[str, Any]
    ) -> StructuredModelResponse:
        """Generate structured JSON output using OpenAI's JSON mode."""
        response = await self._client.chat.completions.create(
            model=self.name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant that outputs valid JSON. Always respond with "
                        "valid JSON only, no markdown formatting."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content or "{}"
        usage = None
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        # Parse the JSON response
        try:
            parsed = cast(dict[str, Any], json.loads(content))
            return StructuredModelResponse(content=parsed, usage=usage)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"OpenRouter returned invalid JSON: {e}") from e


class OpenRouterProvider(Provider):
    """OpenRouter provider."""

    _DEFAULT_MODEL: Final[str] = "openai/gpt-4o-mini"
    _AVAILABLE_MODELS: Final[set[str]] = {
        "openai/gpt-4o-mini",
        "openai/gpt-4o",
        "anthropic/claude-3.5-sonnet",
        "google/gemini-2.0-flash-exp:free",
    }

    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.name: str = "openrouter"
        self._api_key = api_key
        self._base_url = base_url

    def get_model(self, model: str | None = None) -> AIModel:
        """Return an OpenRouter model client."""
        model_name = model or self._DEFAULT_MODEL
        if model_name not in self._AVAILABLE_MODELS:
            raise ValueError(f"Unsupported OpenRouter model '{model_name}'.")
        return OpenRouterModel(model_name, api_key=self._api_key, base_url=self._base_url)
