"""Base interfaces for AI providers and models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol


class ModelResponse(Protocol):
    """Response contract for model outputs."""

    content: str


@dataclass
class SimpleModelResponse:
    """Minimal model response structure."""

    content: str


class AIModel(ABC):
    """Abstract base class for AI models."""

    name: str

    @abstractmethod
    async def generate(self, prompt: str) -> ModelResponse:
        """Generate a response for the given prompt."""


class Provider(ABC):
    """Abstract base class for AI providers."""

    name: str

    @abstractmethod
    def get_model(self, model: str | None = None) -> AIModel:
        """Return the model client for the provider."""
