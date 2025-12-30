"""Base interfaces for AI providers and models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
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
