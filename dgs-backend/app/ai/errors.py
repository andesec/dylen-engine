"""Shared error classification helpers for AI provider handling."""

from __future__ import annotations

from typing import Iterable


_PROVIDER_HINTS: tuple[str, ...] = (
    "unsupported model",
    "model not found",
    "no such model",
    "model is not available",
    "not supported",
    "not available",
    "rate limit",
    "quota",
    "timeout",
    "timed out",
    "connection",
    "network",
    "api key",
    "unauthorized",
    "forbidden",
    "service unavailable",
    "bad gateway",
    "gateway",
    "openrouter",
    "gemini",
)

_OUTPUT_HINTS: tuple[str, ...] = (
    "invalid json",
    "failed to parse",
    "parse json",
    "schema",
    "validation",
)


def _match_hint(message: str, hints: Iterable[str]) -> bool:
    """Return True when any hint appears in the message."""
    # Scan for known substrings to categorize provider vs output errors.
    for hint in hints:
        if hint in message:
            return True
    return False


def is_provider_error(exc: Exception) -> bool:
    """Return True when an exception indicates a provider or model availability failure."""
    message = str(exc).lower()
    return _match_hint(message, _PROVIDER_HINTS)


def is_output_error(exc: Exception) -> bool:
    """Return True when an exception indicates invalid output formatting."""
    message = str(exc).lower()
    return _match_hint(message, _OUTPUT_HINTS)
