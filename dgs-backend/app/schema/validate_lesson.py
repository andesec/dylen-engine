"""Helper for validating lesson payloads."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .lesson_models import LessonDocument
from .widgets_loader import WidgetRegistry, load_widget_registry

DEFAULT_WIDGETS_PATH = Path(__file__).with_name("widgets_prompt.md")


def _collect_registry(path: Path = DEFAULT_WIDGETS_PATH) -> WidgetRegistry:
    """Load the widget registry from the vendored documentation."""

    return load_widget_registry(path)


def _iter_widgets(blocks: Iterable[Any]) -> Iterable[Any]:
    for block in blocks:
        # Subsections do not nest further, so guard against missing attribute.
        yield from block.items
        subsections = getattr(block, "subsections", None)
        if subsections:
            yield from _iter_widgets(subsections)


def validate_lesson(payload: Any) -> tuple[bool, list[str], LessonDocument | None]:
    """
    Validate a lesson payload against the versioned schema and known widgets.

    Returns:
        Tuple where:
        - ok: bool indicating whether validation succeeded.
        - errors: list of human-readable validation errors.
        - model: parsed LessonDocument when validation passes, otherwise None.
    """

    errors: list[str] = []

    model_validator = getattr(LessonDocument, "model_validate", None)
    parse_obj = getattr(LessonDocument, "parse_obj", None)
    parse_method = model_validator or parse_obj

    if parse_method is None:
        raise RuntimeError("LessonDocument does not expose a validation entrypoint.")

    try:
        lesson_model = parse_method(payload)
    except ValidationError as exc:
        errors.extend(f"{err['loc']}: {err['msg']}" for err in exc.errors())
        return False, errors, None

    registry = _collect_registry()
    for widget in _iter_widgets(lesson_model.blocks):
        if not registry.is_known(widget.type):
            errors.append(f"Unknown widget type: {widget.type}")

    if errors:
        return False, errors, None

    return True, errors, lesson_model
