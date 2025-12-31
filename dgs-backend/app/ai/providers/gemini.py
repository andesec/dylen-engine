"""Gemini provider implementation using the new google-genai SDK."""

from __future__ import annotations

import json
import os
from typing import Any, Final, cast

from google import genai
from google.genai import types

from app.ai.providers.base import (
    AIModel,
    ModelResponse,
    Provider,
    SimpleModelResponse,
    StructuredModelResponse,
)


class GeminiModel(AIModel):
    """Gemini model client with structured output support using google-genai SDK."""

    def __init__(self, name: str, api_key: str | None = None) -> None:
        self.name: str = name
        self.supports_structured_output = True

        # Configure Gemini API
        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")

        self._client = genai.Client(api_key=api_key)

    async def generate(self, prompt: str) -> ModelResponse:
        """Generate text response from Gemini."""
        response = self._client.models.generate_content(model=self.name, contents=prompt)
        usage = None
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count,
            }
        return SimpleModelResponse(content=response.text, usage=usage)

    async def generate_structured(
        self, prompt: str, schema: dict[str, Any]
    ) -> StructuredModelResponse:
        """Generate structured JSON output using Gemini's JSON mode."""
        # Use a plain dict for config to avoid pydantic validation errors on JSON Schema
        config: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_json_schema": schema,
        }

        response = self._client.models.generate_content(
            model=self.name,
            contents=prompt,
            config=config,
        )

        usage = None
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count,
            }

        # Parse the JSON response
        try:
            content = cast(dict[str, Any], json.loads(response.text))
            return StructuredModelResponse(content=content, usage=usage)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Gemini returned invalid JSON: {e}") from e


class GeminiProvider(Provider):
    """Gemini provider."""

    _DEFAULT_MODEL: Final[str] = "gemini-2.0-flash"
    _AVAILABLE_MODELS: Final[set[str]] = {
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-pro-latest",
        "gemini-flash-latest",
        "gemini-2.0-flash-exp",
    }

    def __init__(self, api_key: str | None = None) -> None:
        self.name: str = "gemini"
        self._api_key = api_key

    def get_model(self, model: str | None = None) -> AIModel:
        """Return a Gemini model client."""
        model_name = model or self._DEFAULT_MODEL
        if model_name not in self._AVAILABLE_MODELS:
            raise ValueError(f"Unsupported Gemini model '{model_name}'.")
        return GeminiModel(model_name, api_key=self._api_key)
