"""Gemini provider implementation using the new google-genai SDK."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import warnings
from typing import Any, Final, cast

from pydantic.warnings import ArbitraryTypeWarning
from starlette.concurrency import run_in_threadpool

with warnings.catch_warnings():
  warnings.filterwarnings("ignore", message=r"<built-in function any> is not a Python type.*", category=ArbitraryTypeWarning)
  from google import genai
  from google.genai import types

from app.ai.json_parser import parse_json_with_fallback
from app.ai.providers.base import AIModel, ModelResponse, Provider, SimpleModelResponse, StructuredModelResponse


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
    logger = logging.getLogger("app.ai.providers.gemini")

    # Allow deterministic local tests without spending credits.
    dummy = AIModel.load_dummy_response("SECTION_BUILDER")
    if dummy is not None:
      response = SimpleModelResponse(content=dummy, usage=None)
      logger.info("Gemini SECTION_BUILDER dummy response:\n%s", response.content)
      return response

    # Use the async client to avoid blocking the asyncio event loop.
    response = await _with_backoff(self._client.aio.models.generate_content, model=self.name, contents=prompt)

    logger.info("Gemini response:\n%s", response.text)
    usage = None

    if response.usage_metadata:
      usage = {"prompt_tokens": response.usage_metadata.prompt_token_count, "completion_tokens": response.usage_metadata.candidates_token_count, "total_tokens": response.usage_metadata.total_token_count}
    return SimpleModelResponse(content=response.text, usage=usage)

  async def generate_structured(self, prompt: str, schema) -> StructuredModelResponse:
    """Generate structured JSON output using Gemini's JSON mode."""
    logger = logging.getLogger("app.ai.providers.gemini")

    # Allow deterministic local tests without spending credits.
    dummy = AIModel.load_dummy_response("SECTION_BUILDER")
    if dummy is not None:
      cleaned = AIModel.strip_json_fences(dummy)
      parsed = cast(dict[str, Any], parse_json_with_fallback(cleaned))
      response = StructuredModelResponse(content=parsed, usage=None)
      logger.info("Gemini dummy structured response:\n%s", dummy)
      return response

    try:
      # Use a plain dict for config to avoid pydantic validation errors on JSON Schema
      # config: dict[str, Any] = {
      #     "response_mime_type": "application/json",
      #     "response_schema": schema,
      # }
      # Use the async client to avoid blocking the asyncio event loop.
      # Use the async client to avoid blocking the asyncio event loop.
      response = await _with_backoff(self._client.aio.models.generate_content, model=self.name, contents=prompt, config={"response_mime_type": "application/json", "response_schema": schema})

      logger.info("Gemini structured response (raw):\n%s", response.text)
    except Exception as e:
      raise RuntimeError(f"Gemini returned invalid JSON: {e}") from e

    usage = None
    if response.usage_metadata:
      usage = {"prompt_tokens": response.usage_metadata.prompt_token_count, "completion_tokens": response.usage_metadata.candidates_token_count, "total_tokens": response.usage_metadata.total_token_count}

    # Parse the JSON response
    # Parse the model response with a lenient fallback to reduce retry churn.
    try:
      cleaned = self.strip_json_fences(response.text)
      parsed = cast(dict[str, Any], parse_json_with_fallback(cleaned))
      return StructuredModelResponse(content=parsed, usage=usage)
    except json.JSONDecodeError as e:
      raise RuntimeError(f"Gemini returned invalid JSON: {e}") from e

  async def upload_file(self, file_content: bytes, mime_type: str, display_name: str | None = None) -> Any:
    """Upload a file to the Gemini File API."""
    try:
      # Upload using the Google GenAI SDK
      # Note: We need to ensure we're using the synchronous or async method correctly based on SDK version
      # The SDK's client.files.upload seems to be synchronous in the current version we are using,
      # but we are in an async method. For now, running it directly is acceptable if it's fast,
      # or we might need run_in_executor if it strictly blocking.
      # Assuming 2.0 SDK simple usage:
      # Wrap synchronous SDK calls so we don't block the event loop.
      uploaded_file = await run_in_threadpool(self._client.files.upload, file=file_content, config=types.UploadFileConfig(mime_type=mime_type, display_name=display_name))
      return uploaded_file
    except Exception as e:
      raise RuntimeError(f"Gemini file upload failed: {e}") from e

  async def generate_with_files(self, prompt: str, files: list[Any]) -> ModelResponse:
    """Generate text response using prompt and uploaded files."""
    logger = logging.getLogger("app.ai.providers.gemini")

    # Combine files and prompt into contents list
    # files here are expected to be the file objects returned by upload_file (genai.types.File)
    contents = list(files)
    contents.append(prompt)

    try:
      # Use the async client to avoid blocking the asyncio event loop.
      response = await self._client.aio.models.generate_content(model=self.name, contents=contents)
      logger.info("Gemini file-based response:\n%s", response.text)

      usage = None
      if response.usage_metadata:
        usage = {"prompt_tokens": response.usage_metadata.prompt_token_count, "completion_tokens": response.usage_metadata.candidates_token_count, "total_tokens": response.usage_metadata.total_token_count}
      return SimpleModelResponse(content=response.text, usage=usage)
    except Exception as e:
      raise RuntimeError(f"Gemini generation with files failed: {e}") from e

  async def generate_speech(self, text: str, voice: str | None = None) -> bytes:
    """Generate speech audio from text using Gemini."""
    logger = logging.getLogger("app.ai.providers.gemini")

    try:
      # Request audio output
      config = {"response_mime_type": "audio/mp3"}

      # Include voice/style hints when provided, since the SDK does not expose a stable voice selector here.
      voice_hint = f"Voice/style: {voice}\n" if voice else ""
      prompt = f"{voice_hint}Read the following text clearly and naturally:\n\n{text}"

      response = await self._client.aio.models.generate_content(model=self.name, contents=prompt, config=config)

      # Extract audio bytes
      if response.parts:
        for part in response.parts:
          if part.inline_data and part.inline_data.data:
            return part.inline_data.data

      raise RuntimeError("No audio data received from Gemini.")

    except Exception as e:
      logger.error(f"Gemini speech generation failed: {e}")
      raise RuntimeError(f"Gemini speech generation failed: {e}") from e


class GeminiProvider(Provider):
  """Gemini provider."""

  _DEFAULT_MODEL: Final[str] = "gemini-2.0-flash"
  _AVAILABLE_MODELS: Final[set[str]] = {"gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite"}

  def __init__(self, api_key: str | None = None) -> None:
    self.name: str = "gemini"
    self._api_key = api_key

  @property
  def supports_files(self) -> bool:
    return True

  def get_model(self, model: str | None = None) -> AIModel:
    """Return a Gemini model client."""
    model_name = model or self._DEFAULT_MODEL
    if model_name not in self._AVAILABLE_MODELS:
      # Allow fallback attempts to find compatible models even if the exact string isn't in the static set
      # (though normally we'd want strict checking, for now let's be lenient or add the model if it's valid)
      # But to be safe and match previous logic:
      if model_name != self._DEFAULT_MODEL:  # Simple check, or just raise as before
        pass
      # Actually, let's strictly check against _AVAILABLE_MODELS as before
      if model_name not in self._AVAILABLE_MODELS:
        raise ValueError(f"Unsupported Gemini model '{model_name}'.")

    return GeminiModel(model_name, api_key=self._api_key)


async def _with_backoff(func, *args, **kwargs):
  retries = 3
  base_delay = 1
  for i in range(retries):
    try:
      return await func(*args, **kwargs)
    except Exception as e:
      # Check for 429
      if "429" in str(e) or "Too Many Requests" in str(e):
        if i == retries - 1:
          raise
        delay = base_delay * (2**i) + random.uniform(0, 1)
        await asyncio.sleep(delay)
      else:
        raise
  return await func(*args, **kwargs)
