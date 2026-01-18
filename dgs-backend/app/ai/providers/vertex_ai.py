import logging
import os
from typing import Any, Final, cast
import warnings
from pydantic.warnings import ArbitraryTypeWarning

# Suppress Pydantic warnings from google-genai
with warnings.catch_warnings():
  warnings.filterwarnings("ignore", message=r"<built-in function any> is not a Python type.*", category=ArbitraryTypeWarning)
  from google import genai

from app.ai.json_parser import parse_json_with_fallback
from app.ai.providers.base import AIModel, ModelResponse, Provider, SimpleModelResponse, StructuredModelResponse
from app.config import get_settings

logger = logging.getLogger(__name__)


class VertexAIModel(AIModel):
  def __init__(self, name: str, project: str, location: str) -> None:
    self.name = name
    # Initialize client with Vertex AI backend
    self._client = genai.Client(vertexai=True, project=project, location=location)
    self.supports_structured_output = True

  async def generate(self, prompt: str) -> ModelResponse:
    try:
      response = await self._client.aio.models.generate_content(model=self.name, contents=prompt)

      logger.info("Vertex AI response:\n%s", response.text)

      # Extract usage metadata if available
      usage = None
      if response.usage_metadata:
        usage = {
          "prompt_tokens": response.usage_metadata.prompt_token_count,
          "completion_tokens": response.usage_metadata.candidates_token_count,
          "total_tokens": response.usage_metadata.total_token_count,
        }

      return SimpleModelResponse(content=response.text, usage=usage)
    except Exception as e:
      logger.error(f"Vertex AI generation failed: {e}")
      raise

  async def generate_structured(self, prompt: str, schema: Any) -> StructuredModelResponse:
    try:
      # For Vertex AI structured output, we can use response_schema
      response = await self._client.aio.models.generate_content(model=self.name, contents=prompt, config={"response_mime_type": "application/json", "response_schema": schema})

      logger.info("Vertex AI structured response (raw):\n%s", response.text)

      # Extract usage metadata
      usage = None
      if response.usage_metadata:
        usage = {
          "prompt_tokens": response.usage_metadata.prompt_token_count,
          "completion_tokens": response.usage_metadata.candidates_token_count,
          "total_tokens": response.usage_metadata.total_token_count,
        }

      # Parse the JSON response
      content = parse_json_with_fallback(response.text)

      return StructuredModelResponse(content=cast(dict[str, Any], content), usage=usage)
    except Exception as e:
      logger.error(f"Vertex AI structured generation failed: {e}")
      raise


class VertexAIProvider(Provider):
  _DEFAULT_MODEL: Final[str] = "gemini-2.0-flash"
  _AVAILABLE_MODELS: Final[set[str]] = {"gemini-2.0-flash-001", "gemini-2.0-flash", "gemini-2.5-pro", "gemini-3.0-pro", "gemini-3.0-flash", "gemini-pro-latest"}

  def __init__(self) -> None:
    self.name = "vertexai"
    settings = get_settings()
    self.project_id = settings.gcp_project_id
    self.location = settings.gcp_location

    if not self.project_id or not self.location:
      raise ValueError("GCP_PROJECT_ID and GCP_LOCATION must be set for Vertex AI provider.")

  def get_model(self, model: str | None = None) -> AIModel:
    model_name = model or self._DEFAULT_MODEL

    # Handle "vertex-" prefix removal if present
    if model_name.startswith("vertex-"):
      model_name = model_name.replace("vertex-", "")

    return VertexAIModel(model_name, self.project_id, self.location)
