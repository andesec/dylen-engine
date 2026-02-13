"""
Schema export utilities for converting msgspec Structs to Gemini-compatible JSON schemas.

This module provides functions to convert Python msgspec.Struct definitions into
JSON Schema format compatible with Google Gemini API's structured output feature.
"""

from __future__ import annotations

import inspect
from typing import Annotated, Any, Literal, get_args, get_origin

import msgspec


def _get_type_schema(type_hint: Any) -> dict[str, Any]:
  """
  Convert a Python type hint to JSON Schema type definition.

  Args:
      type_hint: Python type annotation or msgspec.inspect type object

  Returns:
      JSON Schema type object
  """
  # Handle msgspec.inspect types
  if isinstance(type_hint, msgspec.inspect.Metadata):
    # Extract the actual type and constraints
    schema = _get_type_schema(type_hint.type)
    pattern = getattr(type_hint, "pattern", None)
    ge = getattr(type_hint, "ge", None)
    le = getattr(type_hint, "le", None)
    extra_json_schema = getattr(type_hint, "extra_json_schema", None)
    if pattern is not None and schema.get("type") == "string":
      schema["pattern"] = pattern
    if ge is not None and schema.get("type") in {"integer", "number"}:
      schema["minimum"] = ge
    if le is not None and schema.get("type") in {"integer", "number"}:
      schema["maximum"] = le
    # Add extra JSON schema properties
    if extra_json_schema:
      schema.update(extra_json_schema)
    return schema

  if isinstance(type_hint, msgspec.inspect.StrType):
    schema = {"type": "string"}
    if type_hint.pattern is not None:
      schema["pattern"] = type_hint.pattern
    return schema

  if isinstance(type_hint, msgspec.inspect.IntType):
    schema = {"type": "integer"}
    if type_hint.ge is not None:
      schema["minimum"] = type_hint.ge
    if type_hint.le is not None:
      schema["maximum"] = type_hint.le
    return schema

  if isinstance(type_hint, msgspec.inspect.FloatType):
    return {"type": "number"}

  if isinstance(type_hint, msgspec.inspect.BoolType):
    return {"type": "boolean"}

  if isinstance(type_hint, msgspec.inspect.ListType):
    return {"type": "array", "items": _get_type_schema(type_hint.item_type)}

  if isinstance(type_hint, msgspec.inspect.TupleType):
    return {"type": "array", "prefixItems": [_get_type_schema(item) for item in type_hint.item_types]}

  if isinstance(type_hint, msgspec.inspect.DictType):
    schema = {"type": "object"}
    if type_hint.value_type:
      schema["additionalProperties"] = _get_type_schema(type_hint.value_type)
    return schema

  if isinstance(type_hint, msgspec.inspect.StructType):
    # This is a nested struct, convert it
    return struct_to_json_schema(type_hint.cls)

  if isinstance(type_hint, msgspec.inspect.LiteralType):
    return {"type": "string", "enum": list(type_hint.values)}

  if isinstance(type_hint, msgspec.inspect.UnionType):
    # Check if it's Optional (union with None)
    types = type_hint.types
    none_types = [t for t in types if isinstance(t, msgspec.inspect.NoneType)]
    non_none_types = [t for t in types if not isinstance(t, msgspec.inspect.NoneType)]

    if none_types and len(non_none_types) == 1:
      # Optional type
      schema = _get_type_schema(non_none_types[0])
      if isinstance(schema.get("type"), str):
        schema["type"] = [schema["type"], "null"]
      return schema
    # Multiple non-None types
    return {"anyOf": [_get_type_schema(t) for t in non_none_types]}

  if isinstance(type_hint, msgspec.inspect.NoneType):
    return {"type": "null"}

  # Handle standard Python type hints (fallback)
  origin = get_origin(type_hint)
  args = get_args(type_hint)

  # Handle None/null
  if type_hint is type(None):
    return {"type": "null"}

  # Handle basic types
  if type_hint is str:
    return {"type": "string"}
  if type_hint is int:
    return {"type": "integer"}
  if type_hint is float:
    return {"type": "number"}
  if type_hint is bool:
    return {"type": "boolean"}

  # Handle Literal (enum)
  if origin is Literal:
    return {"type": "string", "enum": list(args)}

  # Handle Optional (Union with None)
  if origin is type(None) | type or (origin and str(origin) == "typing.Union"):
    # Filter out None to get the actual type
    non_none_types = [arg for arg in args if arg is not type(None)]
    if len(non_none_types) == 1:
      schema = _get_type_schema(non_none_types[0])
      # Add null to type array
      if isinstance(schema.get("type"), str):
        schema["type"] = [schema["type"], "null"]
      return schema
    # Multiple non-None types - use anyOf
    return {"anyOf": [_get_type_schema(t) for t in non_none_types]}

  # Handle tuple (use prefixItems for fixed-size tuples)
  if origin is tuple:
    return {"type": "array", "prefixItems": [_get_type_schema(arg) for arg in args]}

  # Handle list
  if origin is list:
    if args:
      return {"type": "array", "items": _get_type_schema(args[0])}
    return {"type": "array"}

  # Handle dict
  if origin is dict:
    schema = {"type": "object"}
    if args and len(args) == 2:
      schema["additionalProperties"] = _get_type_schema(args[1])
    return schema

  # Handle msgspec.Struct
  if inspect.isclass(type_hint) and issubclass(type_hint, msgspec.Struct):
    return struct_to_json_schema(type_hint)

  # Fallback for Any
  return {}


def _extract_meta_constraints(annotation: Any) -> dict[str, Any]:
  """
  Extract msgspec.Meta constraints from Annotated type.

  Args:
      annotation: Type annotation potentially containing msgspec.Meta

  Returns:
      Dictionary of JSON Schema constraints
  """
  constraints = {}

  # Check if this is an Annotated type
  origin = get_origin(annotation)
  if origin is not Annotated:
    return constraints

  args = get_args(annotation)
  if len(args) < 2:
    return constraints

  # Look for msgspec.Meta in the metadata
  for metadata in args[1:]:
    if isinstance(metadata, msgspec.Meta):
      # Extract constraints
      if hasattr(metadata, "pattern") and metadata.pattern is not None:
        constraints["pattern"] = metadata.pattern
      if hasattr(metadata, "ge") and metadata.ge is not None:
        constraints["minimum"] = metadata.ge
      if hasattr(metadata, "le") and metadata.le is not None:
        constraints["maximum"] = metadata.le
      if hasattr(metadata, "description") and metadata.description is not None:
        constraints["description"] = metadata.description
      if hasattr(metadata, "title") and metadata.title is not None:
        constraints["title"] = metadata.title

  return constraints


def struct_to_json_schema(struct_class: type[msgspec.Struct]) -> dict[str, Any]:
  """
  Convert a msgspec.Struct class to Gemini-compatible JSON schema.

  Args:
      struct_class: msgspec.Struct class to convert

  Returns:
      JSON Schema object with type, properties, required, etc.
  """
  schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

  # Add class docstring as description
  if struct_class.__doc__:
    schema["description"] = struct_class.__doc__.strip()

  # Use msgspec.inspect to get struct field information
  type_info = msgspec.inspect.type_info(struct_class)

  if not isinstance(type_info, msgspec.inspect.StructType):
    raise ValueError(f"{struct_class} is not a msgspec.Struct")

  for field in type_info.fields:
    field_name = field.name
    field_type = field.type

    # Get base type schema
    field_schema = _get_type_schema(field_type)

    # Add Meta constraints if present (from original type annotation)
    # We need to check the original class annotations
    if hasattr(struct_class, "__annotations__"):
      original_annotation = struct_class.__annotations__.get(field_name)
      if original_annotation:
        constraints = _extract_meta_constraints(original_annotation)
        field_schema.update(constraints)

    schema["properties"][field_name] = field_schema

    # Add to required if field is required
    if field.required:
      schema["required"].append(field_name)

  return schema


def build_gemini_config(schema: dict[str, Any], mime_type: str = "application/json") -> dict[str, Any]:
  """
  Build complete Gemini API generation configuration.

  Args:
      schema: JSON Schema object
      mime_type: Response MIME type (default: "application/json")

  Returns:
      Configuration dict for Gemini API with response_mime_type and response_json_schema
  """
  return {"response_mime_type": mime_type, "response_json_schema": schema}


def get_widget_schema(widget_name: str) -> dict[str, Any]:
  """
  Get JSON schema for a specific widget payload.

  Args:
      widget_name: Widget name (e.g., 'markdown', 'flipcards', 'mcqs')

  Returns:
      JSON Schema for the widget payload
  """
  from app.schema.widget_models import (
    AsciiDiagramPayload,
    ChecklistPayload,
    CodeEditorPayload,
    FensterPayload,
    FillBlankPayload,
    FlipCardsPayload,
    FreeTextPayload,
    InputLinePayload,
    InteractiveTerminalPayload,
    MarkdownPayload,
    MCQsInner,
    StepFlowPayload,
    SwipeCardsPayload,
    TerminalDemoPayload,
    TranslationPayload,
    TreeViewPayload,
  )

  widget_map = {
    "markdown": MarkdownPayload,
    "flipcards": FlipCardsPayload,
    "tr": TranslationPayload,
    "fillblank": FillBlankPayload,
    "freeText": FreeTextPayload,
    "inputLine": InputLinePayload,
    "asciiDiagram": AsciiDiagramPayload,
    "interactiveTerminal": InteractiveTerminalPayload,
    "terminalDemo": TerminalDemoPayload,
    "codeEditor": CodeEditorPayload,
    "swipecards": SwipeCardsPayload,
    "stepFlow": StepFlowPayload,
    "checklist": ChecklistPayload,
    "treeview": TreeViewPayload,
    "mcqs": MCQsInner,
    "fenster": FensterPayload,
  }

  if widget_name not in widget_map:
    raise ValueError(f"Unknown widget: {widget_name}")

  return struct_to_json_schema(widget_map[widget_name])
