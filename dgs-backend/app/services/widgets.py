from __future__ import annotations

from functools import lru_cache

from app.schema.service import DEFAULT_WIDGETS_PATH
from app.schema.widgets_loader import load_widget_registry


def _normalize_option_id(value: str) -> str:
    """Normalize option ids to lowercase alphanumeric tokens."""
    # Strip non-alphanumeric characters for stable option ids.
    return "".join(ch for ch in value.lower() if ch.isalnum())


@lru_cache(maxsize=1)
def _widget_id_map() -> dict[str, str]:
    """Build a mapping from normalized widget ids to canonical widget keys."""
    # Load widget registry once to align client ids with schema keys.

    registry = load_widget_registry(DEFAULT_WIDGETS_PATH)
    mapping: dict[str, str] = {}

    for widget_name in registry.available_types():
        normalized = _normalize_option_id(widget_name)
        mapping[normalized] = widget_name

    return mapping


def _normalize_widget_ids(widgets: list[str]) -> list[str]:
    """Normalize widget ids to canonical registry keys."""
    widget_map = _widget_id_map()
    normalized: list[str] = []

    for widget in widgets:
        # Normalize widget ids so schema validation uses canonical keys.
        widget_id = _normalize_option_id(widget)

        if widget_id not in widget_map:
            raise ValueError(f"Unsupported widget id '{widget}'.")

        normalized.append(widget_map[widget_id])

    return normalized
