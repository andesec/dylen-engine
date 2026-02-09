from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import msgspec

from app.schema.section_normalizer import normalize_lesson_section_keys
from app.schema.widget_models import LessonDocument, Section

DEFAULT_WIDGETS_PATH = Path(__file__).with_name("widgets_prompt.md")
SchemaDict = dict[str, Any]
SectionPayload = dict[str, Any]
SectionValidationResult = tuple[bool, list[str], SectionPayload | None]
logger = logging.getLogger(__name__)


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
    """
    # Start with the full schema
    schema = self.section_schema()
    defs = schema.get("$defs", {}) or schema.get("definitions", {})

    # Find the WidgetItem definition
    # In msgspec schemas, definitions are usually keyed by class name
    widget_item_def = defs.get("WidgetItem")

    if widget_item_def and "properties" in widget_item_def:
      # Filter properties to only include allowed widgets
      current_props = widget_item_def["properties"]
      filtered_props = {k: v for k, v in current_props.items() if k in allowed_widgets}

      # Update the definition in place
      widget_item_def["properties"] = filtered_props

    return schema

  def sanitize_schema(self, schema: dict[str, Any], provider_name: str) -> dict[str, Any]:
    """
    Sanitize schema for provider-specific structured output requirements.

    This uses a hybrid approach:
    - Widgets are defined at the root ($defs).
    - Structural elements (Section, Subsection, WidgetItem) are inlined.
    - Constraints are stripped.
    """
    return _simplify_schema(schema)

  def validate_lesson_payload(self, payload: Any) -> ValidationResult:
    """Validate a lesson payload and return structured issues."""
    try:
      normalized_payload = normalize_lesson_section_keys(payload)
      lesson_model = msgspec.convert(normalized_payload, type=LessonDocument)
      return ValidationResult(ok=True, issues=[], model=lesson_model)
    except msgspec.ValidationError as exc:
      issues = [_issue_from_msgspec_error(exc)]
      return ValidationResult(ok=False, issues=issues, model=None)

  def validate_section_payload(self, section_json: SectionPayload, *, topic: str, section_index: int) -> SectionValidationResult:
    """Validate a single section by wrapping it as a lesson payload."""
    wrap = self._wrap_section_for_validation
    payload = wrap(section_json, topic=topic, section_index=section_index)
    result = self.validate_lesson_payload(payload)
    if not result.ok and _is_overlong_only_issues(result.issues):
      messages = _issues_to_messages(result.issues)
      for message in messages:
        logger.warning("Over-limit content accepted during section validation: %s", message)
      return True, messages, section_json
    if not result.ok or result.model is None or not result.model.blocks:
      return False, _issues_to_messages(result.issues), None
    return True, _issues_to_messages(result.issues), section_json

  def widget_schemas_for_types(self, widget_types: list[str]) -> dict[str, Any]:
    """
    Return widget JSON schemas keyed by widget type label.
    """
    schemas: dict[str, Any] = {}

    # Import here to avoid circular deps if any
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

    type_to_model = {
      "tr": TranslationPayload,
      "flip": FlipPayload,
      "fillblank": FillBlankPayload,
      "swipecards": SwipeCardsPayload,
      "freeText": FreeTextPayload,
      "inputLine": InputLinePayload,
      "stepFlow": StepFlowPayload,
      "asciiDiagram": AsciiDiagramPayload,
      "checklist": ChecklistPayload,
      "interactiveTerminal": InteractiveTerminalPayload,
      "terminalDemo": TerminalDemoPayload,
      "codeEditor": CodeEditorPayload,
      "treeview": TreeViewPayload,
      "mcqs": MCQsInner,
      "table": TablePayload,
      "compare": ComparePayload,
      "markdown": MarkdownPayload,
      "fenster": FensterPayload,
    }

    for widget_type in dict.fromkeys(widget_types):
      model = type_to_model.get(widget_type)
      if model:
        schemas[widget_type] = msgspec.json.schema(model)

    return schemas

  @staticmethod
  def _wrap_section_for_validation(section_json: dict[str, Any], *, topic: str, section_index: int) -> dict[str, Any]:
    return {"title": f"{topic} - Section {section_index}", "blocks": [section_json]}


def _issue_from_msgspec_error(err: msgspec.ValidationError) -> ValidationIssue:
  return ValidationIssue(path="payload", message=str(err), code="validation_error")


def _issues_to_messages(issues: list[ValidationIssue]) -> list[str]:
  return [f"{issue.path}: {issue.message}" for issue in issues]


def _is_overlong_only_issues(issues: list[ValidationIssue]) -> bool:
  """Allow non-blocking validation when failures are only max-length/max-items violations."""
  if not issues:
    return False
  return all(_is_overlong_issue(issue.message) for issue in issues)


def _is_overlong_issue(message: str) -> bool:
  """Detect msgspec errors that are strictly about upper length bounds."""
  lowered = message.lower()
  if "length <=" not in lowered:
    return False
  return "expected `str`" in lowered or "expected `array`" in lowered


def _simplify_schema(schema: dict[str, Any]) -> dict[str, Any]:
  """
  Flatten and simplify the schema while preserving $defs.
  - Keeps $defs at the root.
  - Keeps structural elements (Section, Subsection, etc.) as refs.
  - Recursively cleans all nodes and removes strict size bounds.
  """
  defs = schema.get("$defs", {}) or schema.get("definitions", {})

  def _with_nullable_type(option: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a cleaned option schema into a nullable type schema when possible."""
    option_type = option.get("type")
    if isinstance(option_type, str):
      nullable_option = option.copy()
      nullable_option["type"] = [option_type, "null"]
      return nullable_option
    if isinstance(option_type, list):
      nullable_option = option.copy()
      if "null" not in option_type:
        nullable_option["type"] = [*option_type, "null"]
      return nullable_option
    return None

  def _simplify_union(key: str, options: list[Any], node: dict[str, Any]) -> dict[str, Any]:
    """Simplify anyOf/oneOf while preserving nullable unions required by structured output."""
    cleaned_options = [_clean_node(option) for option in options]
    non_null_options = [option for option in cleaned_options if not (isinstance(option, dict) and option.get("type") == "null")]
    has_null_option = len(non_null_options) != len(cleaned_options)

    # Optional[T] should remain nullable after simplification; convert to type union when possible.
    if has_null_option and len(non_null_options) == 1 and isinstance(non_null_options[0], dict):
      nullable_option = _with_nullable_type(non_null_options[0])
      if nullable_option is not None:
        return nullable_option

    # Collapse single-option unions for cleaner schemas when null is not involved.
    if not has_null_option and len(cleaned_options) == 1 and isinstance(cleaned_options[0], dict):
      return cleaned_options[0]

    union_node = node.copy()
    union_node[key] = cleaned_options
    union_node.pop("type", None)
    return union_node

  def _clean_node(node: Any) -> Any:
    if not isinstance(node, dict):
      return node

    # Handle $ref - convert to standard #/$defs/ format
    if "$ref" in node:
      ref_key = node["$ref"].split("/")[-1]
      return {"$ref": f"#/$defs/{ref_key}"}

    # Simplify anyOf/oneOf (handle Optional)
    for key in ("anyOf", "oneOf"):
      if key in node:
        options = node[key]
        if isinstance(options, list):
          return _simplify_union(key, options, node)

    # Process children
    new_node = node.copy()

    # Strip metadata and state-space-heavy bounds for Gemini compatibility.
    keys_to_remove = ("$defs", "definitions", "title", "$schema", "minItems", "maxItems", "minLength", "maxLength", "additional_properties")
    for k in keys_to_remove:
      new_node.pop(k, None)

    if "properties" in new_node:
      new_node["properties"] = {k: _clean_node(v) for k, v in new_node["properties"].items()}
    elif new_node.get("type") == "object":
      # Gemini likes to know the object can have any properties if not specified
      new_node["additionalProperties"] = True

    if "items" in new_node:
      new_node["items"] = _clean_node(new_node["items"])
    elif "prefixItems" in new_node:
      new_node["prefixItems"] = [_clean_node(item) for item in new_node["prefixItems"]]
      # If prefixItems is used (Tuples), Gemini often requires items: false or items: {}
      if "items" not in new_node:
        new_node["items"] = False
    elif new_node.get("type") == "array":
      # Gemini requires "items" for array types
      new_node["items"] = {}

    # Fix for Gemini: enum must have type: string
    if "enum" in new_node and "type" not in new_node:
      new_node["type"] = "string"

    return new_node

  # Process the root
  cleaned_root = _clean_node(schema)

  # Process all definitions
  final_defs = {}
  for name, definition in defs.items():
    final_defs[name] = _clean_node(definition)

  if final_defs:
    cleaned_root["$defs"] = final_defs

  _enforce_widget_item_schema_requirements(cleaned_root)
  return cleaned_root


def _enforce_widget_item_schema_requirements(schema: dict[str, Any]) -> None:
  """Require at least one known widget key and block unknown widget keys."""
  defs = schema.get("$defs")
  if not isinstance(defs, dict):
    return

  widget_item_schema = defs.get("WidgetItem")
  if not isinstance(widget_item_schema, dict):
    return

  properties = widget_item_schema.get("properties")
  if not isinstance(properties, dict) or not properties:
    return

  property_names = [str(name) for name in properties.keys()]
  # `anyOf` with per-key required clauses enforces at least one widget key.
  widget_item_schema["anyOf"] = [{"required": [name]} for name in property_names]
  widget_item_schema.pop("oneOf", None)
  widget_item_schema["additionalProperties"] = False
  # `required` remains empty; selection is enforced by `anyOf`.
  widget_item_schema["required"] = []
