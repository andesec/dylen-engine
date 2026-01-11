"""Repairer agent implementation."""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from typing import Any, cast

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import format_schema_block, render_repair_prompt
from app.ai.deterministic_repair import attempt_deterministic_repair
from app.ai.pipeline.contracts import JobContext, RepairInput, RepairResult
from app.schema.lesson_models import normalize_widget

JsonDict = dict[str, Any]
Errors = list[str]


@dataclass(frozen=True)
class RepairTarget:
  """Represents a widget entry that needs targeted repair."""

  path: str
  widget: JsonDict
  errors: list[str]
  widget_type: str | None = None


class RepairerAgent(BaseAgent[RepairInput, RepairResult]):
  """Repair invalid JSON sections."""

  name = "Repairer"

  async def run(self, input_data: RepairInput, ctx: JobContext) -> RepairResult:
    """Repair a structured section when validation fails."""
    logger = logging.getLogger(__name__)
    request = ctx.request
    section = input_data.section
    structured = input_data.structured
    errors = structured.validation_errors
    section_json: JsonDict = structured.payload
    topic = request.topic
    section_number = section.section_number
    dummy_json = self._load_dummy_json()

    if dummy_json is not None:
      # Use deterministic fixture output when configured to avoid provider calls.
      validator = self._schema_service.validate_section_payload
      ok, repaired_errors, _ = validator(dummy_json, topic=topic, section_index=section_number)
      err_list = [] if ok else repaired_errors
      return RepairResult(section_number=section_number, fixed_json=dummy_json, changes=["dummy_fixture"], errors=err_list)

    if errors:
      section_json = self._deterministic_repair(section_json, errors, topic, section_number)
      validator = self._schema_service.validate_section_payload
      ok, errors, _ = validator(section_json, topic=topic, section_index=section_number)

      if ok:
        changes = ["deterministic_repair"]
        return RepairResult(section_number=section_number, fixed_json=section_json, changes=changes, errors=[])

    if not errors:
      return RepairResult(section_number=section_number, fixed_json=section_json, changes=[], errors=[])

    # Identify only the widget entries tied to validation failures.
    repair_targets = _collect_repair_targets(section_json, errors)

    if not repair_targets:
      return RepairResult(section_number=section_number, fixed_json=section_json, changes=[], errors=errors)

    widget_types = [target.widget_type for target in repair_targets if target.widget_type]
    widget_schemas = self._schema_service.widget_schemas_for_types(widget_types)
    # Provide minimal context for targeted repairs instead of the full section payload.
    prompt_targets = _serialize_repair_targets(repair_targets)
    prompt_text = render_repair_prompt(request, section, prompt_targets, errors, widget_schemas)
    schema = _build_repair_schema(widget_schemas)

    if self._model.supports_structured_output:
      schema = self._schema_service.sanitize_schema(schema, provider_name=self._provider_name)
      response = await self._model.generate_structured(prompt_text, schema)
      purpose = f"repair_section_{section.section_number}_of_{request.depth}"
      call_index = f"{section.section_number}/{request.depth}"
      self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=response.usage)
      repaired_payload = response.content
    else:
      prompt_parts = [
        prompt_text,
        format_schema_block(schema, label="JSON SCHEMA (Repair Output)"),
        "Output ONLY valid JSON.",
      ]
      prompt_with_schema = "\n\n".join(prompt_parts)
      raw = await self._model.generate(prompt_with_schema)
      purpose = f"repair_section_{section.section_number}_of_{request.depth}"
      call_index = f"{section.section_number}/{request.depth}"
      self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=raw.usage)

      try:
        cleaned = self._model.strip_json_fences(raw.content)
        repaired_payload = cast(dict[str, Any], json.loads(cleaned))
      except json.JSONDecodeError as exc:
        logger.error("Repairer failed to parse JSON: %s", exc)
        raise RuntimeError(f"Failed to parse repaired section JSON: {exc}") from exc

    # Apply only the repaired widget payloads back into their original positions.
    repaired_json = _apply_repairs(section_json, repaired_payload, repair_targets)
    validator = self._schema_service.validate_section_payload
    ok, repaired_errors, _ = validator(repaired_json, topic=topic, section_index=section_number)
    changes = ["ai_repair"]
    err_list = [] if ok else repaired_errors
    return RepairResult(section_number=section_number, fixed_json=repaired_json, changes=changes, errors=err_list)

  @staticmethod
  def _deterministic_repair(section_json: JsonDict, errors: Errors, topic: str, section_number: int) -> JsonDict:
    payload = {"title": f"{topic} - Section {section_number}", "blocks": [section_json]}
    repaired = attempt_deterministic_repair(payload, errors)
    blocks = repaired.get("blocks")

    if isinstance(blocks, list) and blocks:
      first_block = blocks[0]

      if isinstance(first_block, dict):
        return first_block

    return section_json


def _collect_repair_targets(section_json: JsonDict, errors: Errors) -> list[RepairTarget]:
  """Collect widget repair targets from validation errors."""
  errors_by_path: dict[str, list[str]] = {}

  # Normalize error strings into a per-widget bucket keyed by path.

  for path, message in _parse_error_entries(errors):
    target_path = _target_path_from_error(path)

    if target_path is None:
      continue

    errors_by_path.setdefault(target_path, []).append(message)

  targets: list[RepairTarget] = []

  # Resolve each target path into the actual widget payload to repair.

  for target_path, messages in errors_by_path.items():
    payload = _value_at_path(section_json, target_path)

    if payload is None:
      continue

    normalized = _safe_normalize_widget(payload)

    if normalized is None:
      continue

    widget_type = _detect_widget_type(normalized)
    targets.append(RepairTarget(path=target_path, widget=normalized, errors=messages, widget_type=widget_type))

  return targets


def _parse_error_entries(errors: Errors) -> list[tuple[str, str]]:
  """Split error strings into (path, message) pairs."""
  entries: list[tuple[str, str]] = []

  # Preserve the original ordering to keep repairs deterministic.

  for error in errors:

    if ":" in error:
      path, message = error.split(":", 1)
      entries.append((path.strip(), message.strip()))
    else:
      entries.append(("payload", error))

  return entries


def _target_path_from_error(path: str) -> str | None:
  """Derive a widget-level path from a validation error path."""
  tokens = [token for token in path.split(".") if token]

  # Strip the lesson wrapper added during section validation.

  if len(tokens) >= 2 and tokens[0] == "blocks" and tokens[1].isdigit():
    tokens = tokens[2:]

  # Prefer item-level repairs for section items and subsections.

  for index, token in enumerate(tokens):

    if token == "items" and index + 1 < len(tokens):
      return ".".join(tokens[: index + 2])

  return None


def _value_at_path(section_json: JsonDict, path: str) -> Any | None:
  """Return the value at a dot path inside the section JSON."""
  tokens = [token for token in path.split(".") if token]
  current: Any = section_json

  # Walk dict/list containers based on token shape.

  for token in tokens:

    if isinstance(current, list) and token.isdigit():
      index = int(token)

      if index < 0 or index >= len(current):
        return None

      current = current[index]
      continue

    if isinstance(current, dict):

      if token not in current:
        return None

      current = current[token]
      continue

    return None

  return current


def _set_value_at_path(section_json: JsonDict, path: str, value: Any) -> bool:
  """Set a value at a dot path inside the section JSON."""
  tokens = [token for token in path.split(".") if token]

  if not tokens:
    return False

  current: Any = section_json

  # Walk to the parent container so we can replace the target node.

  for token in tokens[:-1]:

    if isinstance(current, list) and token.isdigit():
      index = int(token)

      if index < 0 or index >= len(current):
        return False

      current = current[index]
      continue

    if isinstance(current, dict):

      if token not in current:
        return False

      current = current[token]
      continue

    return False

  last = tokens[-1]

  if isinstance(current, list) and last.isdigit():
    index = int(last)

    if index < 0 or index >= len(current):
      return False

    current[index] = value
    return True

  if isinstance(current, dict):
    current[last] = value
    return True

  return False


def _detect_widget_type(widget: Any) -> str | None:
  """Infer a widget type label from a widget payload."""

  # Handle explicit widget objects as well as shorthand mappings.

  if isinstance(widget, dict):

    if "type" in widget:
      return str(widget["type"])

    if len(widget) == 1:
      return str(next(iter(widget.keys())))

  if isinstance(widget, str):
    return "p"

  return None


def _safe_normalize_widget(widget: Any) -> JsonDict | None:
  """Normalize a widget payload to full form, preserving raw data on failure."""

  # Normalize shorthand into explicit widget objects for schema validation.

  try:
    normalized = normalize_widget(widget)
  except ValueError:

    if isinstance(widget, dict):
      return widget

    return None

  return normalized


def _build_repair_schema(widget_schemas: dict[str, Any]) -> dict[str, Any]:
  """Build a structured-output schema for targeted widget repairs."""
  defs: dict[str, Any] = {}
  any_of: list[dict[str, Any]] = []

  # Merge widget schemas into a compact union with shared $defs.

  for schema in widget_schemas.values():
    schema_defs = schema.get("$defs")

    if isinstance(schema_defs, dict):
      for key, value in schema_defs.items():
        defs.setdefault(key, value)

    schema_copy = dict(schema)
    schema_copy.pop("$defs", None)
    any_of.append(schema_copy)

  if not any_of:
    any_of.append({"type": "object"})

  repair_item_schema = {
    "type": "object",
    "properties": {
      "path": {"type": "string"},
      "widget": {"anyOf": any_of},
    },
    "required": ["path", "widget"],
    "additionalProperties": False,
  }
  output_schema = {
    "type": "object",
    "properties": {"repairs": {"type": "array", "items": repair_item_schema}},
    "required": ["repairs"],
    "additionalProperties": False,
  }

  if defs:
    output_schema["$defs"] = defs

  return output_schema


def _apply_repairs(section_json: JsonDict, repair_payload: Any, targets: list[RepairTarget]) -> JsonDict:
  """Apply repaired widgets to the original section JSON."""
  repaired = copy.deepcopy(section_json)

  # Guard against malformed repair payloads.

  if not isinstance(repair_payload, dict):
    return repaired

  repairs = repair_payload.get("repairs")

  if not isinstance(repairs, list):
    return repaired

  allowed_paths = {target.path for target in targets}

  # Only apply repairs that match known target paths.

  for repair in repairs:

    if not isinstance(repair, dict):
      continue

    path = repair.get("path")
    widget = repair.get("widget")

    if not isinstance(path, str):
      continue

    if path not in allowed_paths:
      continue

    if widget is None:
      continue

    _set_value_at_path(repaired, path, widget)

  return repaired


def _serialize_repair_targets(targets: list[RepairTarget]) -> list[dict[str, Any]]:
  """Serialize repair targets for prompt rendering."""
  serialized: list[dict[str, Any]] = []

  # Keep payloads simple for prompt rendering.

  for target in targets:
    serialized.append({"path": target.path, "widget": target.widget, "errors": target.errors})

  return serialized
