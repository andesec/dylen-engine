"""Serialize lesson models into the shorthand widget format."""

from __future__ import annotations

from typing import Any, cast

from .lesson_models import LessonDocument, SectionBlock, SubsectionBlock, Widget


def _dump_model(model: Any, *, by_alias: bool = False) -> dict[str, Any]:
  dump = getattr(model, "model_dump", None)
  if callable(dump):
    return cast(dict[str, Any], dump(by_alias=by_alias))
  return cast(dict[str, Any], model.dict(by_alias=by_alias))


def _widget_to_shorthand(widget: Widget) -> Any:
  # If it's a model, we can just dump it because the models ARE the shorthand now.
  return _dump_model(widget, by_alias=True)


def _subsection_to_shorthand(subsection: SubsectionBlock) -> dict[str, Any]:
  data: dict[str, Any] = {"subsection": subsection.subsection or subsection.section, "items": [_widget_to_shorthand(widget) for widget in subsection.items]}
  return data


def _section_to_shorthand(section: SectionBlock) -> dict[str, Any]:
  data: dict[str, Any] = {"section": section.section, "items": [_widget_to_shorthand(widget) for widget in section.items]}
  if section.subsections:
    data["subsections"] = [_subsection_to_shorthand(sub) for sub in section.subsections]
  return data


def lesson_to_shorthand(lesson: LessonDocument) -> dict[str, Any]:
  """Serialize a validated lesson into the shorthand widget format."""

  data: dict[str, Any] = {"title": lesson.title, "blocks": [_section_to_shorthand(section) for section in lesson.blocks]}
  return data
