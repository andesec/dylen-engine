"""Routing utilities for provider/model selection."""

from __future__ import annotations

from enum import Enum

from app.ai.providers.base import AIModel, Provider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openrouter import OpenRouterProvider


class ProviderMode(str, Enum):
    """Supported provider modes."""

    GEMINI = "gemini"
    OPENROUTER = "openrouter"


def get_provider_for_mode(mode: str | ProviderMode) -> Provider:
    """Return a provider instance for the given mode."""
    provider_map: dict[str, Provider] = {
        ProviderMode.GEMINI.value: GeminiProvider(),
        ProviderMode.OPENROUTER.value: OpenRouterProvider(),
    }
    key = mode.value if isinstance(mode, ProviderMode) else mode
    try:
        return provider_map[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider mode '{mode}'.") from exc


def get_model_for_mode(mode: str | ProviderMode, model: str | None = None) -> AIModel:
    """Return a model client for the given mode and model name."""
    provider = get_provider_for_mode(mode)
    return provider.get_model(model)
