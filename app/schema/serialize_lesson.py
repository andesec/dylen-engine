"""Serialize msgspec lesson models into shorthand widget format."""

from __future__ import annotations

from typing import Any

from .widget_models import LessonDocument


def lesson_to_shorthand(lesson: LessonDocument) -> dict[str, Any]:
  """Serialize a validated lesson into shorthand widget format."""
  return {"title": lesson.title, "blocks": [section.output() for section in lesson.blocks]}
