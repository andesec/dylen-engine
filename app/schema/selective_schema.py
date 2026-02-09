"""
Selective widget schema generation for Mirascope with msgspec.

This module provides utilities to create custom Section/Subsection models
that only include specific widgets, reducing schema size and token usage.
"""

from __future__ import annotations

from typing import Annotated, Any

import msgspec

from app.schema.widget_models import SUBSECTION_ITEMS_MAX, SUBSECTION_ITEMS_MIN, SUBSECTIONS_PER_SECTION_MAX, SUBSECTIONS_PER_SECTION_MIN, MarkdownPayload, get_widget_payload, get_widget_shorthand_names, resolve_widget_shorthand_name


def _normalize_widget_names(widget_names: list[str]) -> list[str]:
  """Normalize aliases to canonical shorthand widget keys while preserving order."""
  normalized_names: list[str] = []
  seen_names: set[str] = set()
  for widget_name in widget_names:
    canonical_name = resolve_widget_shorthand_name(widget_name)
    if canonical_name in seen_names:
      continue
    seen_names.add(canonical_name)
    normalized_names.append(canonical_name)
  return normalized_names


def create_selective_widget_item(widget_names: list[str]) -> type[msgspec.Struct]:
  """
  Create a WidgetItem class that only includes specified widgets.

  Args:
      widget_names: List of widget names to include (e.g., ['markdown', 'flip', 'mcqs'])

  Returns:
      A new msgspec.Struct class with only the specified widget fields

  Example:
      >>> SelectiveWidgetItem = create_selective_widget_item(['markdown', 'mcqs'])
      >>> # This WidgetItem only has markdown and mcqs fields
  """
  normalized_names = _normalize_widget_names(widget_names)

  # Build field annotations and defaults
  annotations = {}
  defaults = {}

  for widget_name in normalized_names:
    payload_type = get_widget_payload(widget_name)
    # All widget fields are optional
    annotations[widget_name] = payload_type | None
    defaults[widget_name] = None

  def __post_init__(self):  # noqa: N807
    # Ensure exactly one field is set
    set_fields = 0
    for name in normalized_names:
      if getattr(self, name) is not None:
        set_fields += 1

    if set_fields != 1:
      raise ValueError(f"Widget item must have exactly one widget key defined. Found {set_fields}.")

  def output_method(self) -> dict[str, Any]:
    """Return the shorthand object for the active widget."""
    for name in normalized_names:
      val = getattr(self, name)
      if val is not None:
        return {name: val.output()}
    return {}

  # Create the class dynamically using type() to ensure defaults are registered correctly
  # msgspec.Struct uses the class dictionary at creation time to determine fields and defaults
  class_dict = {"__annotations__": annotations, "__post_init__": __post_init__, "output": output_method, **defaults}

  return type("WidgetItem", (msgspec.Struct,), class_dict)


def create_selective_subsection(widget_names: list[str]) -> type[msgspec.Struct]:
  """
  Create a Subsection class that only allows specified widgets.

  Args:
      widget_names: List of widget names to include

  Returns:
      A new Subsection msgspec.Struct class
  """
  widget_item = create_selective_widget_item(widget_names)

  # Create the class dynamically to avoid forward reference issues
  def output_method(self) -> dict[str, Any]:
    return {"section": self.section, "items": [item.output() for item in self.items], "subsections": []}

  class_dict = {
    "__annotations__": {
      "section": Annotated[str, msgspec.Meta(min_length=1, description="Subsection title")],
      "items": Annotated[list[widget_item], msgspec.Meta(min_length=SUBSECTION_ITEMS_MIN, max_length=SUBSECTION_ITEMS_MAX, description=f"Widget items ({SUBSECTION_ITEMS_MIN}-{SUBSECTION_ITEMS_MAX})")],
    },
    "output": output_method,
  }

  return type("Subsection", (msgspec.Struct,), class_dict)


def create_selective_section(widget_names: list[str]) -> type[msgspec.Struct]:
  """
  Create a Section class that only allows specified widgets.

  Args:
      widget_names: List of widget names to include

  Returns:
      A new Section msgspec.Struct class

  Example:
      >>> # For outcomes agent (only markdown + mcqs)
      >>> OutcomesSection = create_selective_section(['markdown', 'mcqs'])
      >>>
      >>> # For section builder (6 specific widgets)
      >>> SectionBuilderSection = create_selective_section([
      ...     'markdown', 'flip', 'tr', 'fillblank', 'table', 'mcqs'
      ... ])
  """
  subsection_cls = create_selective_subsection(widget_names)

  # Create the class dynamically to avoid forward reference issues
  # msgspec needs to resolve type annotations, and subsection_cls is a local variable
  class_dict = {
    "__annotations__": {
      "section": Annotated[str, msgspec.Meta(min_length=1, description="Section title")],
      "markdown": Annotated[MarkdownPayload, msgspec.Meta(description="Section introduction")],
      "subsections": Annotated[list[subsection_cls], msgspec.Meta(min_length=SUBSECTIONS_PER_SECTION_MIN, max_length=SUBSECTIONS_PER_SECTION_MAX, description=f"Subsections ({SUBSECTIONS_PER_SECTION_MIN}-{SUBSECTIONS_PER_SECTION_MAX})")],
    },
    "output": lambda self: {"section": self.section, "items": [{"markdown": self.markdown.output()}] if self.markdown else [], "subsections": [s.output() for s in self.subsections]},
  }

  return type("Section", (msgspec.Struct,), class_dict)


def create_selective_lesson(widget_names: list[str]) -> type[msgspec.Struct]:
  """
  Create a LessonDocument class that only allows specified widgets.

  Args:
      widget_names: List of widget names to include

  Returns:
      A new LessonDocument msgspec.Struct class
  """
  section_cls = create_selective_section(widget_names)

  # Create the class dynamically to avoid forward reference issues
  class_dict = {"__annotations__": {"title": Annotated[str, msgspec.Meta(max_length=60, description="Lesson title")], "blocks": Annotated[list[section_cls], msgspec.Meta(description="List of sections")]}}

  return type("LessonDocument", (msgspec.Struct,), class_dict)


# Pre-defined common configurations
def get_outcomes_section() -> type[msgspec.Struct]:
  """Get Section class for outcomes agent (markdown + mcqs only)."""
  return create_selective_section(["markdown", "mcqs"])


def get_section_builder_section() -> type[msgspec.Struct]:
  """Get Section class for section builder agent (6 core widgets)."""
  return create_selective_section(["markdown", "flip", "tr", "fillblank", "table", "mcqs"])


def get_full_section() -> type[msgspec.Struct]:
  """Get Section class with all available widgets."""
  return create_selective_section(get_widget_shorthand_names())
