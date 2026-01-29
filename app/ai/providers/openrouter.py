"""OpenRouter provider implementation using openai SDK."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Final, cast

from openai import AsyncOpenAI

from app.ai.json_parser import parse_json_with_fallback
from app.ai.providers.base import AIModel, ModelResponse, Provider, SimpleModelResponse, StructuredModelResponse


class OpenRouterModel(AIModel):
  """OpenRouter model client with structured output support."""

  _STRUCTURED_OUTPUT_MODELS: Final[set[str]] = {"openai/gpt-oss-20b:free", "openai/gpt-oss-120b:free"}

  def __init__(self, name: str, api_key: str | None = None, base_url: str | None = None) -> None:
    self.name: str = name
    self.supports_structured_output = name in self._STRUCTURED_OUTPUT_MODELS

    # Configure OpenRouter client
    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
      raise ValueError("OPENROUTER_API_KEY environment variable is required")

    # OpenRouter uses the OpenAI-compatible API; we add optional attribution headers.
    default_headers = {}
    referer = os.getenv("OPENROUTER_HTTP_REFERER")
    if referer:
      default_headers["HTTP-Referer"] = referer
    title = os.getenv("OPENROUTER_TITLE")
    if title:
      default_headers["X-Title"] = title

    self._client = AsyncOpenAI(api_key=api_key, base_url=base_url or "https://openrouter.ai/api/v1", default_headers=default_headers or None)

  async def generate(self, prompt: str) -> ModelResponse:
    """Generate text response from OpenRouter."""
    logger = logging.getLogger("app.ai.providers.openrouter")

    # Allow deterministic local tests without spending credits.
    dummy = AIModel.load_dummy_response("GATHERER")
    if dummy is not None:
      response = SimpleModelResponse(content=dummy, usage=None)
      logger.info("OpenRouter GATHERER dummy response:\n%s", response.content)
      return response

    response = await self._client.chat.completions.create(model=self.name, messages=[{"role": "user", "content": prompt}])

    content = response.choices[0].message.content or ""
    logger.info("OpenRouter response:\n%s", content)
    usage = None

    if response.usage:
      usage = {"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens, "total_tokens": response.usage.total_tokens}

    return SimpleModelResponse(content=content, usage=usage)

  async def generate_structured(self, prompt: str, schema: dict[str, Any]) -> StructuredModelResponse:
    """Generate structured JSON output using OpenAI's JSON mode."""
    logger = logging.getLogger("app.ai.providers.openrouter")

    if not self.supports_structured_output:
      raise RuntimeError(f"Structured output is not supported for model '{self.name}'.")

    # Allow deterministic local tests without spending credits.
    dummy = AIModel.load_dummy_response("STRUCTURER")
    if dummy is not None:
      cleaned = AIModel.strip_json_fences(dummy)
      parsed = cast(dict[str, Any], parse_json_with_fallback(cleaned))
      response = StructuredModelResponse(content=parsed, usage=None)
      logger.info("OpenRouter dummy structured response:\n%s", dummy)
      return response

    # OpenRouter/OpenAI structured output requires a schema in response_format
    # for strict enforcement, or at least 'json_schema' type.

    # Serialize schema for prompt injection (reinforcement)
    schema_str = json.dumps(schema, indent=2)
    system_msg = f"You are a helpful assistant that outputs valid JSON.\nYou MUST strictly output JSON adhering to this schema:\n```json\n{schema_str}\n```\nOutput valid JSON only, no markdown formatting."

    response = await self._client.chat.completions.create(
      model=self.name,
      messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}],
      response_format={
        "type": "json_schema",
        "json_schema": {
          "name": "lesson_response",
          "schema": schema,
          "strict": True,  # Best effort strictness
        },
      },
    )

    content = response.choices[0].message.content or "{}"
    logger.info("OpenRouter structured response (raw):\n%s", content)
    usage = None

    if response.usage:
      usage = {"prompt_tokens": response.usage.prompt_tokens, "completion_tokens": response.usage.completion_tokens, "total_tokens": response.usage.total_tokens}

    # Parse the JSON response
    # Parse the model response with a lenient fallback to reduce retry churn.
    try:
      cleaned = self.strip_json_fences(content)
      parsed = cast(dict[str, Any], parse_json_with_fallback(cleaned))
      return StructuredModelResponse(content=parsed, usage=usage)
    except json.JSONDecodeError as e:
      raise RuntimeError(f"OpenRouter returned invalid JSON: {e}") from e


class OpenRouterProvider(Provider):
  """OpenRouter provider."""

  _DEFAULT_MODEL: Final[str] = "openai/gpt-oss-20b:free"
  _AVAILABLE_MODELS: Final[set[str]] = {
    # KnowledgeBuilder options (from integration specs).
    "xiaomi/mimo-v2-flash:free",
    "meta-llama/llama-3.1-405b-instruct:free",
    "deepseek/deepseek-r1-0528:free",
    "openai/gpt-oss-120b:free",
    # Structurer options (from integration specs).
    "openai/gpt-oss-20b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
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
