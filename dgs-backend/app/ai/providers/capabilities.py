"""Provider capability definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapabilities:
    """Capability metadata for a provider/model combination."""

    supports_json_schema: bool
    max_schema_depth: int | None = None
    max_enum_size: int | None = None
    notes: str | None = None


def get_provider_capabilities(provider_name: str) -> ProviderCapabilities:
    """Return basic capability info for a provider."""
    name = provider_name.lower()
    if name == "gemini":
        return ProviderCapabilities(supports_json_schema=True, max_schema_depth=8, max_enum_size=50)
    if name == "openrouter":
        return ProviderCapabilities(
            supports_json_schema=True, max_schema_depth=10, max_enum_size=100
        )
    return ProviderCapabilities(supports_json_schema=False)
