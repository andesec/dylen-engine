"""Base interfaces for AI providers and models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Protocol


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

    async def generate_structured(self, prompt: str, schema: dict[str, Any]) -> StructuredModelResponse:
        """Generate structured output that conforms to the provided JSON schema."""
        raise RuntimeError("Structured output is not supported by this model.")


class Provider(ABC):
    """Abstract base class for AI providers."""

    name: str

    @abstractmethod
    def get_model(self, model: str | None = None) -> AIModel:
        """Return the model client for the provider."""


def load_dummy_response(*, expect_json: bool) -> ModelResponse | StructuredModelResponse | None:
    """
    Load a deterministic dummy response from disk when testing the pipeline.

    Set DGS_DUMMY_RESPONSE_PATH to a file containing either plain text (for generate)
    or JSON (for generate_structured). This allows local tests without LLM credits.
    """
    # Separate toggles/paths let tests mix text and JSON outputs without confusion.
    use_dummy_text = os.getenv("DGS_USE_DUMMY_TEXT", "false").lower() == "true"
    use_dummy_json = os.getenv("DGS_USE_DUMMY_JSON", "false").lower() == "true"

    if expect_json and not use_dummy_json:
        return None
    if not expect_json and not use_dummy_text:
        return None

    dummy_path = os.getenv("DGS_DUMMY_JSON_PATH" if expect_json else "DGS_DUMMY_TEXT_PATH")
    if not dummy_path:
        return None
    path = Path(dummy_path)
    if not path.is_absolute():
        # Resolve relative paths from the repo root to keep local fixtures predictable.
        repo_root = Path(__file__).resolve().parents[4]
        path = repo_root / path
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    if expect_json:
        payload = json.loads(content)
        return StructuredModelResponse(content=payload, usage=None)
    return SimpleModelResponse(content=content, usage=None)
