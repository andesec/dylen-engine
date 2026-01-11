"""Routing utilities for provider/model selection."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from app.ai.providers.base import AIModel, Provider
from app.ai.providers.audit import instrument_model

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
    # Wrap provider models to capture audit telemetry without changing call sites.
    model_client = provider.get_model(model)
    provider_name = getattr(provider, "name", mode.value if isinstance(mode, ProviderMode) else str(mode))
    return instrument_model(model_client, provider_name)
