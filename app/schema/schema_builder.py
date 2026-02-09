"""
Dynamic schema builder for generating minimal, token-optimized schemas for Gemini API.

This module provides utilities to build schemas containing only the widgets needed
for a specific context, reducing token usage and improving API efficiency.
"""

from __future__ import annotations

from typing import Any

from app.schema.schema_export import build_gemini_config, struct_to_json_schema
from app.schema.widget_models import (
  SECTION_TITLE_MIN_CHARS,
  SUBSECTION_ITEMS_MAX,
  SUBSECTION_ITEMS_MIN,
  SUBSECTION_TITLE_MIN_CHARS,
  SUBSECTIONS_PER_SECTION_MAX,
  SUBSECTIONS_PER_SECTION_MIN,
  MarkdownPayload,
  get_widget_payload,
  get_widget_shorthand_names,
  resolve_widget_shorthand_name,
)

TABLE_LIKE_WIDGETS = {"table", "compare"}


def _string_schema(min_length: int, description: str) -> dict[str, Any]:
  """Build string constraints for schema output without hard max bounds."""
  return {"type": "string", "minLength": min_length, "description": description}


def _normalize_widget_names(widget_names: list[str]) -> list[str]:
  """Normalize aliases to canonical shorthand keys while preserving order."""
  normalized_names: list[str] = []
  seen_names: set[str] = set()
  for widget_name in widget_names:
    canonical_name = resolve_widget_shorthand_name(widget_name)
    if canonical_name in seen_names:
      continue
    seen_names.add(canonical_name)
    normalized_names.append(canonical_name)
  return normalized_names


def get_widget_dependencies(widget_names: list[str]) -> set[type]:
  """
  Get all payload types needed for the specified widgets.

  Args:
      widget_names: List of widget names (e.g., ['markdown', 'flip', 'mcqs'])

  Returns:
      Set of payload class types needed
  """
  dependencies: set[type] = set()
  for widget_name in _normalize_widget_names(widget_names):
    if widget_name in TABLE_LIKE_WIDGETS:
      continue
    dependencies.add(get_widget_payload(widget_name))
  return dependencies


def build_widget_item_schema(widget_names: list[str]) -> dict[str, Any]:
  """
  Build a WidgetItem schema containing only the specified widgets.

  Args:
      widget_names: List of widget names to include

  Returns:
      JSON Schema for WidgetItem with only specified widgets
  """
  normalized_names = _normalize_widget_names(widget_names)

  # Get dependencies
  payload_types = get_widget_dependencies(normalized_names)

  # Build schema definitions for each payload
  definitions = {}
  for payload_type in payload_types:
    definitions[payload_type.__name__] = struct_to_json_schema(payload_type)

  # Build WidgetItem schema with only specified widgets
  widget_item_schema = {
    "type": "object",
    "description": "Container for any widget type (Mutually Exclusive)",
    "properties": {},
    "oneOf": [],  # Enforce exactly one widget is set
  }

  # Add each widget as a property
  for widget_name in normalized_names:
    if widget_name in TABLE_LIKE_WIDGETS:
      # Keep shorthand schema for table/compare widgets.
      widget_item_schema["properties"][widget_name] = {"type": "array", "items": {"type": "array", "items": {"type": "string"}}}
      continue
    payload_type = get_widget_payload(widget_name)
    widget_item_schema["properties"][widget_name] = {"$ref": f"#/$defs/{payload_type.__name__}"}

  # Add oneOf constraint (exactly one widget must be set)
  for widget_name in normalized_names:
    widget_item_schema["oneOf"].append({"required": [widget_name]})

  return widget_item_schema, definitions


def build_section_schema(widget_names: list[str]) -> dict[str, Any]:
  """
  Build a complete Section schema with only specified widgets.

  Args:
      widget_names: List of widget names to include in items

  Returns:
      JSON Schema for Section with minimal widget set
  """
  widget_item_schema, definitions = build_widget_item_schema(widget_names)

  # Build Subsection schema
  subsection_schema = {
    "type": "object",
    "description": "Subsection model",
    "properties": {
      "title": _string_schema(SUBSECTION_TITLE_MIN_CHARS, "Subsection title"),
      "items": {"type": "array", "items": widget_item_schema, "minItems": SUBSECTION_ITEMS_MIN, "maxItems": SUBSECTION_ITEMS_MAX, "description": f"Widget items ({SUBSECTION_ITEMS_MIN}-{SUBSECTION_ITEMS_MAX})"},
    },
    "required": ["title", "items"],
  }

  # Build Section schema
  section_schema = {
    "type": "object",
    "description": "Section model",
    "properties": {
      "section": _string_schema(SECTION_TITLE_MIN_CHARS, "Section title"),
      "markdown": {"$ref": "#/$defs/MarkdownPayload"},
      "subsections": {"type": "array", "items": subsection_schema, "minItems": SUBSECTIONS_PER_SECTION_MIN, "maxItems": SUBSECTIONS_PER_SECTION_MAX, "description": f"Subsections ({SUBSECTIONS_PER_SECTION_MIN}-{SUBSECTIONS_PER_SECTION_MAX})"},
    },
    "required": ["section", "markdown", "subsections"],
  }

  # Always include MarkdownPayload for section.markdown
  if MarkdownPayload.__name__ not in definitions:
    definitions[MarkdownPayload.__name__] = struct_to_json_schema(MarkdownPayload)

  return {"type": "object", "properties": section_schema["properties"], "required": section_schema["required"], "$defs": definitions}


def build_lesson_schema(widget_names: list[str]) -> dict[str, Any]:
  """
  Build a complete LessonDocument schema with only specified widgets.

  Args:
      widget_names: List of widget names to include

  Returns:
      JSON Schema for LessonDocument optimized for specified widgets
  """
  section_schema = build_section_schema(widget_names)

  return {
    "type": "object",
    "description": "Root lesson document",
    "properties": {
      "title": {"type": "string", "description": "Lesson title"},
      "blocks": {"type": "array", "items": {"type": "object", "properties": section_schema["properties"], "required": section_schema["required"]}, "description": "List of sections"},
    },
    "required": ["title", "blocks"],
    "$defs": section_schema.get("$defs", {}),
  }


def build_schema_for_context(context: str, widget_names: list[str] | None = None) -> dict[str, Any]:
  """
  Build a schema for a specific agent context.

  Args:
      context: Context name ('outcomes', 'section_builder', 'full')
      widget_names: Optional list of widget names (overrides context defaults)

  Returns:
      Complete Gemini API config with response_mime_type and response_json_schema
  """
  # Default widget sets for common contexts
  context_widgets = {"outcomes": ["markdown", "mcqs"], "section_builder": ["markdown", "flip", "tr", "fillblank", "table", "mcqs"], "full": get_widget_shorthand_names()}

  if widget_names is None:
    if context not in context_widgets:
      raise ValueError(f"Unknown context: {context}. Provide widget_names explicitly.")
    widget_names = context_widgets[context]

  # Build the schema
  schema = build_lesson_schema(widget_names)

  # Return Gemini config
  return build_gemini_config(schema)
