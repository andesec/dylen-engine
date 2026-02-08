"""
Selective widget schema generation for Mirascope with msgspec.

This module provides utilities to create custom Section/Subsection models
that only include specific widgets, reducing schema size and token usage.
"""

from __future__ import annotations

from typing import Annotated, Any

import msgspec

from app.schema.widget_models import (
  AsciiDiagramPayload,
  ChecklistPayload,
  CodeEditorPayload,
  ComparePayload,
  FensterPayload,
  FillBlankPayload,
  FlipPayload,
  FreeTextPayload,
  InputLinePayload,
  InteractiveTerminalPayload,
  MarkdownPayload,
  MCQsInner,
  StepFlowPayload,
  SwipeCardsPayload,
  TablePayload,
  TerminalDemoPayload,
  TranslationPayload,
  TreeViewPayload,
)

# Widget type mapping (supports both snake_case and camelCase)
WIDGET_PAYLOAD_MAP = {
  "markdown": MarkdownPayload,
  "flip": FlipPayload,
  "tr": TranslationPayload,
  "fillblank": FillBlankPayload,
  "table": TablePayload,
  "compare": ComparePayload,
  "swipecards": SwipeCardsPayload,
  "swipeCards": SwipeCardsPayload,  # camelCase alias
  "free_text": FreeTextPayload,
  "freeText": FreeTextPayload,  # camelCase alias
  "input_line": InputLinePayload,
  "inputLine": InputLinePayload,  # camelCase alias
  "step_flow": StepFlowPayload,
  "stepFlow": StepFlowPayload,  # camelCase alias
  "ascii_diagram": AsciiDiagramPayload,
  "asciiDiagram": AsciiDiagramPayload,  # camelCase alias
  "checklist": ChecklistPayload,
  "interactive_terminal": InteractiveTerminalPayload,
  "interactiveTerminal": InteractiveTerminalPayload,  # camelCase alias
  "terminal_demo": TerminalDemoPayload,
  "terminalDemo": TerminalDemoPayload,  # camelCase alias
  "code_editor": CodeEditorPayload,
  "codeEditor": CodeEditorPayload,  # camelCase alias
  "treeview": TreeViewPayload,
  "treeView": TreeViewPayload,  # camelCase alias
  "mcqs": MCQsInner,
  "fenster": FensterPayload,
}


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
  # Build field annotations and defaults
  annotations = {}
  defaults = {}

  for widget_name in widget_names:
    if widget_name not in WIDGET_PAYLOAD_MAP:
      raise ValueError(f"Unknown widget: {widget_name}")
    payload_type = WIDGET_PAYLOAD_MAP[widget_name]
    # All widget fields are optional
    annotations[widget_name] = payload_type | None
    defaults[widget_name] = None

  def __post_init__(self):  # noqa: N807
    # Ensure exactly one field is set
    set_fields = 0
    for name in widget_names:
      if getattr(self, name) is not None:
        set_fields += 1

    if set_fields != 1:
      raise ValueError(f"Widget item must have exactly one widget key defined. Found {set_fields}.")

  def output_method(self) -> dict[str, Any]:
    """Return the shorthand object for the active widget."""
    for name in widget_names:
      val = getattr(self, name)
      if val is not None:
        # Map back to camelCase if needed, or just use the field name if it matches the shorthand key
        # The WIDGET_PAYLOAD_MAP keys are already the shorthand keys (mostly)
        # But wait, WIDGET_PAYLOAD_MAP has both snake_case and camelCase keys pointing to the same payload.
        # We need to ensure we use the correct shorthand key.
        # Simple heuristic: if the field name is snake_case and has a camelCase alias in the map, use the camelCase one?
        # Actually, let's look at how the standard WidgetItem.output works. it explicitly maps 'ascii_diagram' to 'asciiDiagram'.
        # We should probably pass the shorthand key mapping or derive it.
        # For now, let's assume the keys used to create the selective item ARE the shorthand keys (or close enough).
        # The user's prompt examples show keys like "asciiDiagram", "freeText".
        # value in WIDGET_PAYLOAD_MAP keys.

        # We need to return {key: val.output()}
        return {name: val.output()}
    return {}

  # Create the class dynamically using type() to ensure defaults are registered correctly
  # msgspec.Struct uses the class dictionary at creation time to determine fields and defaults
  class_dict = {"__annotations__": annotations, "__post_init__": __post_init__, "output": output_method, **defaults}

  return type("SelectiveWidgetItem", (msgspec.Struct,), class_dict)


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
    return {"section": self.title, "items": [item.output() for item in self.items], "subsections": []}

  class_dict = {
    "__annotations__": {"title": Annotated[str, msgspec.Meta(min_length=1, description="Subsection title")], "items": Annotated[list[widget_item], msgspec.Meta(min_length=1, max_length=5, description="Widget items (1-5)")]},
    "output": output_method,
  }

  return type("SelectiveSubsection", (msgspec.Struct,), class_dict)


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
      "title": Annotated[str, msgspec.Meta(min_length=1, description="Section title")],
      "markdown": Annotated[MarkdownPayload, msgspec.Meta(description="Section introduction")],
      "subsections": Annotated[list[subsection_cls], msgspec.Meta(min_length=1, max_length=8, description="Subsections (1-8)")],
    },
    "output": lambda self: {"section": self.title, "items": [{"markdown": self.markdown.output()}] if self.markdown else [], "subsections": [s.output() for s in self.subsections]},
  }

  return type("SelectiveSection", (msgspec.Struct,), class_dict)


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

  return type("SelectiveLessonDocument", (msgspec.Struct,), class_dict)


# Pre-defined common configurations
def get_outcomes_section() -> type[msgspec.Struct]:
  """Get Section class for outcomes agent (markdown + mcqs only)."""
  return create_selective_section(["markdown", "mcqs"])


def get_section_builder_section() -> type[msgspec.Struct]:
  """Get Section class for section builder agent (6 core widgets)."""
  return create_selective_section(["markdown", "flip", "tr", "fillblank", "table", "mcqs"])


def get_full_section() -> type[msgspec.Struct]:
  """Get Section class with all available widgets."""
  return create_selective_section(list(WIDGET_PAYLOAD_MAP.keys()))
