"""Schema loading, sanitization, and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schema.lesson_models import LessonDocument, SectionBlock
from app.schema.widgets_loader import load_widget_registry

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
    """Return the lesson JSON schema and ensure widget registry is loaded."""
    json_schema: dict[str, Any] = LessonDocument.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")
    load_widget_registry(self._widgets_path)
    return json_schema

  def section_schema(self) -> dict[str, Any]:
    """Return the section JSON schema and ensure widget registry is loaded."""
    json_schema: dict[str, Any] = SectionBlock.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")
    load_widget_registry(self._widgets_path)
    return json_schema

  def sanitize_schema(self, schema: dict[str, Any], provider_name: str) -> dict[str, Any]:
    """Sanitize schema for provider-specific structured output requirements."""
    if provider_name.lower() == "gemini":
      return _sanitize_schema_for_gemini(schema, root_schema=schema)
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

    registry = load_widget_registry(self._widgets_path)
    for widget in _iter_widgets(lesson_model.blocks):
      if not registry.is_known(widget.type):
        message = f"Unknown widget type: {widget.type}"
        issues.append(ValidationIssue(path="widget.type", message=message))

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

  @staticmethod
  def _wrap_section_for_validation(section_json: dict[str, Any], *, topic: str, section_index: int) -> dict[str, Any]:
    return {"title": f"{topic} - Section {section_index}", "blocks": [section_json]}


def _iter_widgets(blocks: list[Any]) -> list[Any]:
  items: list[Any] = []
  for block in blocks:
    items.extend(block.items)
    subsections = getattr(block, "subsections", None)
    if subsections:
      items.extend(_iter_widgets(subsections))
  return items


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

  allowed_keys: set[str] = {
    "type",
    "properties",
    "items",
    "anyOf",
    "oneOf",
    "allOf",
    "enum",
    "format",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "minLength",
    "maxLength",
    "pattern",
  }

  sanitized: dict[str, Any] = {k: v for k, v in schema.items() if k in allowed_keys}

  if "properties" in sanitized:
    props = sanitized.get("properties")
    if isinstance(props, dict):
      sanitized["properties"] = {
        key: _sanitize_schema_for_gemini(value, root_schema, visited) for key, value in props.items()
      }
    elif not props:
      sanitized["properties"] = {}

  if "items" in sanitized:
    sanitized["items"] = _sanitize_schema_for_gemini(sanitized["items"], root_schema, visited)

  for key in ("anyOf", "oneOf", "allOf"):
    if key in sanitized and isinstance(sanitized[key], list):
      sanitized[key] = [_sanitize_schema_for_gemini(item, root_schema, visited) for item in sanitized[key]]

  return sanitized
