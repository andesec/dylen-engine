from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import msgspec

from app.schema.widget_models import LessonDocument, Section

DEFAULT_WIDGETS_PATH = Path(__file__).with_name("widgets_prompt.md")
SchemaDict = dict[str, Any]
SectionPayload = dict[str, Any]
SectionValidationResult = tuple[bool, list[str], SectionPayload | None]
VisitedRefs = set[str] | None

DEFAULT_WIDGETS_PATH = Path(__file__).with_name("widgets_prompt.md")
SchemaDict = dict[str, Any]
SectionPayload = dict[str, Any]
SectionValidationResult = tuple[bool, list[str], SectionPayload | None]
VisitedRefs = set[str] | None


@dataclass(frozen=True)
class ValidationIssue:
  """Structured validation issue details."""

  path: str
  message: str
  code: str | None = None


@dataclass(frozen=True)
class ValidationResult:
  """Validation result for a lesson or section."""

  ok: bool
  issues: list[ValidationIssue]
  model: LessonDocument | None = None


class SchemaService:
  """Centralized schema handling and validation."""

  def __init__(self, widgets_path: Path | None = None) -> None:
    self._widgets_path = widgets_path or DEFAULT_WIDGETS_PATH

  def lesson_schema(self) -> dict[str, Any]:
    """Return the lesson JSON schema."""
    return msgspec.json.schema(LessonDocument)

  def section_schema(self) -> dict[str, Any]:
    """Return the section JSON schema."""
    return msgspec.json.schema(Section)

  def subset_section_schema(self, allowed_widgets: list[str]) -> dict[str, Any]:
    """
    Return a section schema restricted to a specific list of widgets.

    Args:
        allowed_widgets: List of allowed widget keys (e.g. ['markdown', 'mcqs']).
    """
    # Start with the full schema
    schema = self.section_schema()
    defs = schema.get("$defs", {})

    # The WidgetItem definition contains the optional fields for each widget type
    widget_item_def = defs.get("WidgetItem")
    if not widget_item_def:
      # Fallback if structure unexpectedly changes
      return schema

    properties = widget_item_def.get("properties", {})

    # Filter properties to only include allowed widgets
    # Note: 'markdown' is often intrinsic, but we respect allowed_widgets strictly if provided.
    filtered_props = {}
    for key, value in properties.items():
      if key in allowed_widgets:
        filtered_props[key] = value

    if filtered_props:
      widget_item_def["properties"] = filtered_props
      # Also update required list if necessary (though WidgetItem fields are optional in struct,
      # __post_init__ enforces one set. Schema usually doesn't enforce __post_init__ logic directly
      # but validation will fail later if empty).

    # Prune unused definitions definition
    self._prune_definitions(schema)

    return schema

  def _prune_definitions(self, schema: dict[str, Any]) -> None:
    """Prune unreachable definitions from the schema."""
    defs = schema.get("$defs", {})
    if not defs:
      return

    visited = set()
    stack = [schema]

    while stack:
      item = stack.pop()
      if isinstance(item, dict):
        for k, v in item.items():
          # Check for $ref
          if k == "$ref" and isinstance(v, str):
            ref_name = v.split("/")[-1]
            if ref_name not in visited and ref_name in defs:
              visited.add(ref_name)
              stack.append(defs[ref_name])

          # Recurse into dict values
          elif isinstance(v, (dict, list)):
            stack.append(v)

      elif isinstance(item, list):
        stack.extend(item)

    schema["$defs"] = {k: v for k, v in defs.items() if k in visited}

  def sanitize_schema(self, schema: dict[str, Any], provider_name: str) -> dict[str, Any]:
    """Sanitize schema for provider-specific structured output requirements."""
    if provider_name.lower() == "gemini":
      return _sanitize_schema_for_gemini(schema, root_schema=schema)
    if provider_name.lower() == "vertexai":
      return _sanitize_schema_for_vertex(schema, root_schema=schema)
    return schema

  def validate_lesson_payload(self, payload: Any) -> ValidationResult:
    """Validate a lesson payload and return structured issues."""
    try:
      # Use msgspec.convert to validate and convert flexible input (dicts) to struct
      lesson_model = msgspec.convert(payload, type=LessonDocument)
      return ValidationResult(ok=True, issues=[], model=lesson_model)
    except msgspec.ValidationError as exc:
      issues = [_issue_from_msgspec_error(exc)]
      return ValidationResult(ok=False, issues=issues, model=None)

  def validate_section_payload(self, section_json: SectionPayload, *, topic: str, section_index: int) -> SectionValidationResult:
    """Validate a single section by wrapping it as a lesson payload."""
    wrap = self._wrap_section_for_validation
    payload = wrap(section_json, topic=topic, section_index=section_index)
    result = self.validate_lesson_payload(payload)
    if not result.ok or result.model is None or not result.model.blocks:
      return False, _issues_to_messages(result.issues), None
    return True, _issues_to_messages(result.issues), section_json

  def widget_schemas_for_types(self, widget_types: list[str]) -> dict[str, Any]:
    """
    Return widget JSON schemas keyed by widget type label.
    """
    schemas: dict[str, Any] = {}

    from app.schema.widget_models import (
      AsciiDiagramWidget,
      ChecklistWidget,
      CodeEditorWidget,
      CompareWidget,
      FillBlankWidget,
      FlipWidget,
      FreeTextWidget,
      InputLineWidget,
      InteractiveTerminalWidget,
      MarkdownTextWidget,
      MCQsWidget,
      StepFlowWidget,
      SwipeCardsWidget,
      TableWidget,
      TerminalDemoWidget,
      TranslationWidget,
      TreeViewWidget,
    )

    TYPE_TO_MODEL = {  # noqa: N806
      "tr": TranslationWidget,
      "flip": FlipWidget,
      "fillblank": FillBlankWidget,
      "swipecards": SwipeCardsWidget,
      "freeText": FreeTextWidget,
      "inputLine": InputLineWidget,
      "stepFlow": StepFlowWidget,
      "asciiDiagram": AsciiDiagramWidget,
      "checklist": ChecklistWidget,
      "interactiveTerminal": InteractiveTerminalWidget,
      "terminalDemo": TerminalDemoWidget,
      "codeEditor": CodeEditorWidget,
      "treeview": TreeViewWidget,
      "mcqs": MCQsWidget,
      "table": TableWidget,
      "compare": CompareWidget,
      "markdown": MarkdownTextWidget,
    }

    for widget_type in dict.fromkeys(widget_types):
      model = TYPE_TO_MODEL.get(widget_type)
      if model:
        # msgspec doesn't have a direct model_json_schema per struct if not top-level
        # But we can generate schema for the type.
        schemas[widget_type] = msgspec.json.schema(model)

    return schemas

  @staticmethod
  def _wrap_section_for_validation(section_json: dict[str, Any], *, topic: str, section_index: int) -> dict[str, Any]:
    return {"title": f"{topic} - Section {section_index}", "blocks": [section_json]}


def _issue_from_msgspec_error(err: msgspec.ValidationError) -> ValidationIssue:
  """Convert msgspec error to structured issue."""
  # msgspec errors are strings, path info is unfortunately embedded or missing in simple convert
  # We just return the message for now.
  return ValidationIssue(path="payload", message=str(err), code="validation_error")


def _issue_from_pydantic_error(err: dict[str, Any]) -> ValidationIssue:
  """Deprecated: Convert pydantic error to structured issue."""
  path = ".".join(str(part) for part in err.get("loc", []))
  message = str(err.get("msg", "Invalid payload."))
  return ValidationIssue(path=path or "payload", message=message, code=err.get("type"))


def _issues_to_messages(issues: list[ValidationIssue]) -> list[str]:
  return [f"{issue.path}: {issue.message}" for issue in issues]


def _sanitize_schema_for_gemini(schema: Any, root_schema: SchemaDict | None = None, visited: VisitedRefs = None) -> Any:
  """
  Sanitize a JSON Schema for Gemini structured output.

  This strips unsupported keys, resolves $refs, and avoids empty properties.
  """
  if visited is None:
    visited = set()

  if schema is None:
    return {"type": "object", "properties": {}}

  if isinstance(schema, str):
    return {"type": "object", "properties": {}}

  if isinstance(schema, (int, float, bool)):
    # Gemini SDK crashes on boolean schemas (e.g. False for forbidden items)
    # We convert to empty object (allow-all) to prevent crash.
    return {"type": "object", "properties": {}}

  if isinstance(schema, list):
    out: list[Any] = []
    for item in schema:
      if isinstance(item, dict):
        out.append(_sanitize_schema_for_gemini(item, root_schema, visited))
    return out

  if not isinstance(schema, dict):
    return {"type": "object", "properties": {}}

  if "$ref" in schema:
    ref_path = schema["$ref"]
    if ref_path in visited:
      return {"type": "object", "properties": {}}
    if root_schema:
      defs = root_schema.get("$defs") or root_schema.get("definitions")
      if defs and isinstance(defs, dict):
        parts = ref_path.split("/")
        if len(parts) >= 3:
          def_name = parts[-1]
          if def_name in defs:
            new_visited = visited.copy()
            new_visited.add(ref_path)
            return _sanitize_schema_for_gemini(defs[def_name], root_schema, new_visited)
    return {"type": "object", "properties": {}}

  allowed_keys: set[str] = {"type", "properties", "items", "anyOf", "oneOf", "allOf", "enum", "format", "minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength", "pattern", "required"}

  sanitized: dict[str, Any] = {k: v for k, v in schema.items() if k in allowed_keys}

  if "properties" in sanitized:
    props = sanitized.get("properties")
    if isinstance(props, dict):
      sanitized["properties"] = {key: _sanitize_schema_for_gemini(value, root_schema, visited) for key, value in props.items()}
    elif not props:
      sanitized["properties"] = {}

  if "items" in sanitized:
    sanitized["items"] = _sanitize_schema_for_gemini(sanitized["items"], root_schema, visited)

  for key in ("anyOf", "oneOf", "allOf"):
    if key in sanitized and isinstance(sanitized[key], list):
      sanitized[key] = [_sanitize_schema_for_gemini(item, root_schema, visited) for item in sanitized[key]]

  return sanitized


def _sanitize_schema_for_vertex(schema: Any, root_schema: SchemaDict | None = None, visited: VisitedRefs = None) -> Any:
  """
  Sanitize a JSON Schema for Vertex AI structured output.

  This includes specific flattening logic for anyOf unions to avoid SDK crashes.
  """
  if visited is None:
    visited = set()

  if schema is None:
    return {"type": "object", "properties": {}}

  if isinstance(schema, str):
    return {"type": "object", "properties": {}}

  if isinstance(schema, (int, float, bool)):
    return schema

  if isinstance(schema, list):
    out: list[Any] = []
    for item in schema:
      if isinstance(item, dict):
        out.append(_sanitize_schema_for_vertex(item, root_schema, visited))
    return out

  if not isinstance(schema, dict):
    return {"type": "object", "properties": {}}

  if "$ref" in schema:
    ref_path = schema["$ref"]
    if ref_path in visited:
      return {"type": "object", "properties": {}}
    if root_schema:
      defs = root_schema.get("$defs") or root_schema.get("definitions")
      if defs and isinstance(defs, dict):
        parts = ref_path.split("/")
        if len(parts) >= 3:
          def_name = parts[-1]
          if def_name in defs:
            new_visited = visited.copy()
            new_visited.add(ref_path)
            return _sanitize_schema_for_vertex(defs[def_name], root_schema, new_visited)
    return {"type": "object", "properties": {}}

  # Flatten anyOf/oneOf if they contain objects
  if "anyOf" in schema or "oneOf" in schema:
    options = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(options, list):
      merged_props = {}
      for opt in options:
        sanitized_opt = _sanitize_schema_for_vertex(opt, root_schema, visited)
        if isinstance(sanitized_opt, dict) and sanitized_opt.get("type") == "object":
          props = sanitized_opt.get("properties", {})
          merged_props.update(props)

      if merged_props:
        return {
          "type": "object",
          "properties": merged_props,
          "required": [],  # All optional in the flattened super-object
        }

  allowed_keys: set[str] = {"type", "properties", "items", "anyOf", "oneOf", "allOf", "enum", "format", "minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength", "pattern", "required"}

  sanitized: dict[str, Any] = {k: v for k, v in schema.items() if k in allowed_keys}

  if "properties" in sanitized:
    props = sanitized.get("properties")
    if isinstance(props, dict):
      sanitized["properties"] = {key: _sanitize_schema_for_vertex(value, root_schema, visited) for key, value in props.items()}
    elif not props:
      sanitized["properties"] = {}

  if "items" in sanitized:
    sanitized["items"] = _sanitize_schema_for_vertex(sanitized["items"], root_schema, visited)

  for key in ("anyOf", "oneOf", "allOf"):
    if key in sanitized and isinstance(sanitized[key], list):
      sanitized[key] = [_sanitize_schema_for_vertex(item, root_schema, visited) for item in sanitized[key]]

  return sanitized
