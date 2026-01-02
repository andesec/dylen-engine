"""Base interfaces for AI providers and models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
from typing import Any, Protocol

from app.utils.env import default_env_path, load_env_file
from botocore.signers import add_generate_db_auth_token


class ModelResponse(Protocol):
  """Response contract for model outputs."""

  content: str
  usage: dict[str, int] | None


@dataclass
class SimpleModelResponse:
  """Minimal model response structure."""

  content: str
  usage: dict[str, int] | None = None


@dataclass
class StructuredModelResponse:
  """Structured model response structure."""

  content: dict[str, Any]
  usage: dict[str, int] | None = None


class AIModel(ABC):
  """Abstract base class for AI models."""

  name: str
  supports_structured_output: bool = False

  @abstractmethod
  async def generate(self, prompt: str) -> ModelResponse:
    """Generate a response for the given prompt."""

  @abstractmethod
  async def generate_structured(
      self, prompt: str, schema: dict[str, Any]
  ) -> StructuredModelResponse:
    """Generate structured output that conforms to the provided JSON schema."""
    raise RuntimeError("Structured output is not supported by this model.")

  @staticmethod
  def strip_json_fences(raw: str) -> str:
    stripped = raw.strip()
    stripped = re.sub(r"^```([A-Za-z0-9#.])*", "", stripped)
    stripped = re.sub(r"```$", "", stripped)
    return stripped.strip()

  @staticmethod
  def load_dummy_response(agent: str) -> str | None:
    """
    Load a deterministic dummy response from disk when testing the pipeline.

    Args:
        agent: Environment variable suffix to select dummy data (e.g., "GATHERER", "STRUCTURER")

    Returns:
        StructuredModelResponse with content as dict, or None if not enabled/found
    """
    if os.getenv(f"DGS_USE_DUMMY_{agent}_RESPONSE", "false").lower() != "true":
      return None

    dummy_path = os.getenv(f"DGS_DUMMY_{agent}_RESPONSE_PATH")
    if not dummy_path:
      raise RuntimeError(f"DGS_DUMMY_{agent}_RESPONSE_PATH not found!")

    path = Path(dummy_path)
    if not path.is_absolute():
      repo_root = Path(__file__).resolve().parents[4]
      path = repo_root / path

      with open(path, "r", encoding="utf-8") as handle:
        return handle.read().strip()

class Provider(ABC):
  """Abstract base class for AI providers."""

  name: str

  @abstractmethod
  def get_model(self, model: str | None = None) -> AIModel:
    """Return the model client for the provider."""
