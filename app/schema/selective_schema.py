"""
Selective widget schema generation for Mirascope with msgspec.

This module provides utilities to create custom Section/Subsection models
that only include specific widgets, reducing schema size and token usage.
"""

from __future__ import annotations

from typing import Annotated

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
  # Build field annotations
  annotations = {}
  for widget_name in widget_names:
    if widget_name not in WIDGET_PAYLOAD_MAP:
      raise ValueError(f"Unknown widget: {widget_name}")
    payload_type = WIDGET_PAYLOAD_MAP[widget_name]
    annotations[widget_name] = payload_type | None

  # Create the class dynamically
  # Note: msgspec.Struct types cannot define __init__, validation happens at construction time
  class SelectiveWidgetItem(msgspec.Struct):
    __annotations__ = annotations

  return SelectiveWidgetItem


def create_selective_subsection(widget_names: list[str]) -> type[msgspec.Struct]:
  """
  Create a Subsection class that only allows specified widgets.

  Args:
      widget_names: List of widget names to include

  Returns:
      A new Subsection msgspec.Struct class
  """
  widget_item = create_selective_widget_item(widget_names)

  class SelectiveSubsection(msgspec.Struct):
    title: Annotated[str, msgspec.Meta(min_length=1, description="Subsection title")]
    items: Annotated[list[widget_item], msgspec.Meta(min_length=1, max_length=5, description="Widget items (1-5)")]

  return SelectiveSubsection


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
  subsection = create_selective_subsection(widget_names)

  class SelectiveSection(msgspec.Struct):
    section: Annotated[str, msgspec.Meta(min_length=1, description="Section title")]
    markdown: Annotated[MarkdownPayload, msgspec.Meta(description="Section introduction")]
    subsections: Annotated[list[subsection], msgspec.Meta(min_length=1, max_length=8, description="Subsections (1-8)")]

  return SelectiveSection


def create_selective_lesson(widget_names: list[str]) -> type[msgspec.Struct]:
  """
  Create a LessonDocument class that only allows specified widgets.

  Args:
      widget_names: List of widget names to include

  Returns:
      A new LessonDocument msgspec.Struct class
  """
  section = create_selective_section(widget_names)

  class SelectiveLessonDocument(msgspec.Struct):
    title: Annotated[str, msgspec.Meta(max_length=60, description="Lesson title")]
    blocks: Annotated[list[section], msgspec.Meta(description="List of sections")]

  return SelectiveLessonDocument


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
