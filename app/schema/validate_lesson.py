"""Helper for validating lesson payloads."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .lesson_models import LessonDocument
from .markdown_limits import collect_overlong_markdown_errors


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

  model_validator = getattr(LessonDocument, "model_validate", None)
  if model_validator is None:
    # Fallback for older Pydantic or if not present (unlikely)
    raise RuntimeError("LessonDocument does not expose a validation entrypoint.")

  try:
    lesson_model = model_validator(payload)
  except ValidationError as exc:
    for err in exc.errors():
      loc = ".".join(str(x) for x in err["loc"])
      errors.append(f"{loc}: {err['msg']}")
    return False, errors, None

  # Enforce runtime-configurable markdown limits after schema validation so the core schema remains stable.
  errors.extend(collect_overlong_markdown_errors(payload, max_markdown_chars=max_markdown_chars))
  if errors:
    return False, errors, None

  # Pydantic validation is now sufficient as it validates structure, types, and values.
  # No need for external registry check because the models define the allowable widgets.

  return True, errors, lesson_model
