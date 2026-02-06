"""Schema loading, sanitization, and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schema.lesson_models import LessonDocument, SectionBlock

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
    json_schema: dict[str, Any] = LessonDocument.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")
    return json_schema

  def section_schema(self) -> dict[str, Any]:
    """Return the section JSON schema."""
    json_schema: dict[str, Any] = SectionBlock.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")
    return json_schema

  def subset_section_schema(self, allowed_widgets: list[str]) -> dict[str, Any]:
    """
    Return a section schema restricted to a specific list of widgets.

    Args:
        allowed_widgets: List of allowed widget keys (e.g. ['markdown', 'mcqs']).
    """
    # Start with the full schema
    schema = self.section_schema()

    # 1. Inspect definitions to identify the main Widget union.
    # We navigate from SectionBlock -> items -> items to find the widget definition.
    defs = schema.get("$defs", {})
    widget_def = None

    # Path: SectionBlock -> items (list) -> items (schema for array elements)
    props = schema.get("properties", {})
    items_prop = props.get("items", {})
    inner_items = items_prop.get("items", {})

    if "$ref" in inner_items:
      ref_name = inner_items["$ref"].split("/")[-1]
      widget_def = defs.get(ref_name)
    elif "anyOf" in inner_items:
      widget_def = inner_items

    if not widget_def or "anyOf" not in widget_def:
      # Fallback if structure isn't as expected: return full schema
      return schema

    # 2. Filter the anyOf list
    original_options = widget_def["anyOf"]
    filtered_options = []

    for option in original_options:
      # Check simple scalar types (not used for widgets in this schema).
      if option.get("type") == "string":
        continue

      # Check referenced definitions (object widgets)
      ref = option.get("$ref")
      if not ref:
        # Unknown shape, decided to exclude or keep?
        # Safest to exclude if we are restricting, but let's keep if unsure?
        # No, strict restriction is better.
        continue

      # Ref format: #/$defs/ChecklistWidget
      def_name = ref.split("/")[-1]
      model_def = defs.get(def_name)

      if not model_def:
        continue

      # Identify widget type by its properties.
      # Most widgets have a single key like "checklist", "mcqs", "p" (explicit).
      properties = model_def.get("properties", {})

      # Check if any of the property keys match our allowed list
      match = False
      for prop_key in properties.keys():
        if prop_key in allowed_widgets:
          match = True
          break

      if match:
        filtered_options.append(option)

    # 3. Update the schema with filtered options
    if filtered_options:
      widget_def["anyOf"] = filtered_options

      # 4. Prune unused definitions to prevent context leakage
      reachable = set()
      # Initialize stack with the filtered options to find initial refs
      stack = list(filtered_options)
      # Also add all root properties to ensure definitions like 'SubsectionBlock' and the main 'Widget' union are reachable
      stack.extend(props.values())

      while stack:
        item = stack.pop()
        if isinstance(item, dict):
          for k, v in item.items():
            if k == "$ref" and isinstance(v, str):
              # Extract definition name from reference (e.g. "#/$defs/MyWidget")
              ref_name = v.split("/")[-1]
              if ref_name not in reachable and ref_name in defs:
                reachable.add(ref_name)
                # Add the definition itself to stack to find nested refs
                stack.append(defs[ref_name])
            elif isinstance(v, (dict, list)):
              stack.append(v)
        elif isinstance(item, list):
          stack.extend(item)

      # Apply pruning
      if "$defs" in schema:
        schema["$defs"] = {k: v for k, v in defs.items() if k in reachable}
    else:
      # If nothing matches, we shouldn't return an unusable schema.
      pass

    return schema

  def sanitize_schema(self, schema: dict[str, Any], provider_name: str) -> dict[str, Any]:
    """Sanitize schema for provider-specific structured output requirements."""
    if provider_name.lower() == "gemini":
      return _sanitize_schema_for_gemini(schema, root_schema=schema)
    if provider_name.lower() == "vertexai":
      return _sanitize_schema_for_vertex(schema, root_schema=schema)
    return schema

  def validate_lesson_payload(self, payload: Any) -> ValidationResult:
    """Validate a lesson payload and return structured issues."""
    parse_method = getattr(LessonDocument, "model_validate", None) or getattr(LessonDocument, "parse_obj", None)
    if parse_method is None:
      raise RuntimeError("LessonDocument does not expose a validation entrypoint.")

    issues: list[ValidationIssue] = []
    try:
      lesson_model = parse_method(payload)
    except ValidationError as exc:
      for err in exc.errors():
        issues.append(_issue_from_pydantic_error(err))
      return ValidationResult(ok=False, issues=issues, model=None)

    # Note: Previously we checked against widgets_loader, but now Pydantic validation is sufficient
    # as the models strictly define the allowed structures.

    model = lesson_model if not issues else None
    return ValidationResult(ok=not issues, issues=issues, model=model)

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
    Deprecated: With shorthand, types are keys in the JSON, not separate discriminators.
    However, we can return the schema for the specific Pydantic model corresponding to the key.
    """
    schemas: dict[str, Any] = {}

    # Map shorthand keys to Pydantic models in lesson_models.py
    # We need to import them dynamically or have a mapping.
    # Since this function might be used by prompts, we need to decide if we still support it.
    # If the prompts need the schema for "tr", we return TranslationWidget.model_json_schema()

    from app.schema.lesson_models import (
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
        schemas[widget_type] = model.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")

    return schemas

  @staticmethod
  def _wrap_section_for_validation(section_json: dict[str, Any], *, topic: str, section_index: int) -> dict[str, Any]:
    return {"title": f"{topic} - Section {section_index}", "blocks": [section_json]}


def _issue_from_pydantic_error(err: dict[str, Any]) -> ValidationIssue:
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
    return schema

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
