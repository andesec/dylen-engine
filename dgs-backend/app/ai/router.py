"""Routing utilities for provider/model selection."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from app.ai.providers.base import AIModel, Provider

if TYPE_CHECKING:
    from app.ai.providers.gemini import GeminiProvider
    from app.ai.providers.openrouter import OpenRouterProvider


class ProviderMode(str, Enum):
    """Supported provider modes."""

    GEMINI = "gemini"
    OPENROUTER = "openrouter"


def get_provider_for_mode(mode: str | ProviderMode) -> Provider:
    """Return a provider instance for the given mode."""
    key = mode.value if isinstance(mode, ProviderMode) else mode
    if key == ProviderMode.GEMINI.value:
        from app.ai.providers.gemini import GeminiProvider

        return GeminiProvider()
    if key == ProviderMode.OPENROUTER.value:
        from app.ai.providers.openrouter import OpenRouterProvider

        return OpenRouterProvider()
    raise ValueError(f"Unsupported provider mode '{mode}'.")


def get_model_for_mode(mode: str | ProviderMode, model: str | None = None) -> AIModel:
    """Return a model client for the given mode and model name."""
    provider = get_provider_for_mode(mode)
    return provider.get_model(model)
