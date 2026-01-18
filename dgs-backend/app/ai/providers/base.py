"""Base interfaces for AI providers and models."""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.utils.env import default_env_path, load_env_file

_ENV_LOADED = False


def _ensure_env_loaded() -> None:
    """Load the repo .env once so dummy flags work outside the API process."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    load_env_file(default_env_path(), override=False)
    _ENV_LOADED = True


def _resolve_dummy_path(agent: str, raw_path: str | None) -> Path:
    """Resolve a dummy response path using env or default fixtures."""
    base_dir = Path(__file__).resolve().parents[4]
    if raw_path:
        path = Path(raw_path)
    else:
        path = base_dir / "fixtures" / f"dummy_{agent.lower()}_response.md"
    if not path.is_absolute():
        path = base_dir / path
    if not path.is_file():
        raise RuntimeError(f"Dummy response path not found for {agent}: {path}")
    return path


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
        _ensure_env_loaded()
        flag = os.getenv(f"DGS_USE_DUMMY_{agent}_RESPONSE", "false").strip().lower()
        if flag not in {"true", "1", "yes", "on"}:
            return None

        path = _resolve_dummy_path(agent, os.getenv(f"DGS_DUMMY_{agent}_RESPONSE_PATH"))

        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()


class Provider(ABC):
    """Abstract base class for AI providers."""

    name: str

    @abstractmethod
    def get_model(self, model: str | None = None) -> AIModel:
        """Return the model client for the provider."""
