"""Helper for validating lesson payloads."""

from __future__ import annotations

from typing import Any

import msgspec

from .markdown_limits import collect_overlong_markdown_errors
from .widget_models import LessonDocument


def validate_lesson(payload: Any, *, max_markdown_chars: int = 1500) -> tuple[bool, list[str], LessonDocument | None]:
  """
  Validate a lesson payload against the versioned schema and known widgets.

  Returns:
      Tuple where:
      - ok: bool indicating whether validation succeeded.
      - errors: list of human-readable validation errors.
      - model: parsed LessonDocument when validation passes, otherwise None.
  """

  errors: list[str] = []

  try:
    # Use msgspec to convert/validate the payload
    lesson_model = msgspec.convert(payload, LessonDocument)
  except msgspec.ValidationError as exc:
    errors.append(str(exc))
    return False, errors, None

  # Enforce runtime-configurable markdown limits after schema validation so the core schema remains stable.
  errors.extend(collect_overlong_markdown_errors(payload, max_markdown_chars=max_markdown_chars))
  if errors:
    return False, errors, None

  return True, errors, lesson_model
