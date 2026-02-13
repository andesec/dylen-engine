"""Repairer agent implementation."""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from typing import Any

import msgspec

from app.ai.agents.base import BaseAgent
from app.ai.agents.prompts import render_repair_prompt
from app.ai.errors import is_output_error
from app.ai.json_parser import parse_json_with_fallback
from app.ai.pipeline.contracts import JobContext, RepairInput, RepairResult
from app.schema.selective_schema import create_selective_widget_item
from app.telemetry.context import llm_call_context

JsonDict = dict[str, Any]
Errors = list[str]


def _prune_none_values(value: Any) -> Any:
  """Preserve `None` placeholders to keep fixed-position payloads intact."""
  return value


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
    """Run repair logic with a catch-all to prevent worker crashes."""
    logger = logging.getLogger(__name__)
    try:
      return await self._run_impl(input_data, ctx)
    except Exception as exc:  # noqa: BLE001
      logger.error("Repairer failed unexpectedly.", exc_info=True)
      section_number = int(input_data.section.section_number)
      original_payload = input_data.structured.payload if isinstance(input_data.structured.payload, dict) else {}
      return RepairResult(section_number=section_number, fixed_json=original_payload, changes=[], errors=[f"repairer_failed: {exc}"])

  async def _run_impl(self, input_data: RepairInput, ctx: JobContext) -> RepairResult:
    """Repair a structured section when validation fails."""
    request = ctx.request
    section = input_data.section
    structured = input_data.structured
    errors = structured.validation_errors
    section_json: JsonDict = structured.payload
    persisted_section_id = structured.db_section_id
    topic = request.topic
    section_number = section.section_number
    dummy_json = self._load_dummy_json()

    if dummy_json is not None:
      # Use deterministic fixture output when configured to avoid provider calls.
      validator = self._schema_service.validate_section_payload
      ok, repaired_errors, _ = validator(dummy_json, topic=topic, section_index=section_number)
      err_list = [] if ok else repaired_errors
      if not err_list:
        await _persist_repaired_section(section_id=persisted_section_id, repaired_json=dummy_json)
      return RepairResult(section_number=section_number, fixed_json=dummy_json, changes=["dummy_fixture"], errors=err_list)

    if errors:
      # Apply manual subsection fixes (titles/items) before invoking AI repair.
      section_json, manual_changes = _apply_subsection_fallbacks(section_json, errors)

      if manual_changes:
        # Re-validate only when manual fixes were applied.
        validator = self._schema_service.validate_section_payload
        ok, errors, _ = validator(section_json, topic=topic, section_index=section_number)

        if ok:
          await _persist_repaired_section(section_id=persisted_section_id, repaired_json=section_json)
          return RepairResult(section_number=section_number, fixed_json=section_json, changes=manual_changes, errors=[])

    if not errors:
      await _persist_repaired_section(section_id=persisted_section_id, repaired_json=section_json)
      return RepairResult(section_number=section_number, fixed_json=section_json, changes=[], errors=[])

    # Identify only the widget entries tied to validation failures.
    repair_targets = _collect_repair_targets(section_json, errors)

    if not repair_targets:
      return RepairResult(section_number=section_number, fixed_json=section_json, changes=[], errors=errors)

    widget_types = [target.widget_type for target in repair_targets if target.widget_type]
    unique_widget_types = list(set(widget_types))

    from app.schema.widget_models import RepairResponse as CanonicalRepairResponse

    if unique_widget_types:
      widget_item_cls = create_selective_widget_item(unique_widget_types)

      # Define response model dynamically
      repair_item_cls = type("RepairItem", (msgspec.Struct,), {"__annotations__": {"path": str, "widget": widget_item_cls}})

      schema_response_cls = type("RepairResponse", (msgspec.Struct,), {"__annotations__": {"repairs": list[repair_item_cls]}})
    else:
      # Fallback to full schema
      schema_response_cls = CanonicalRepairResponse

    # Provide minimal context for targeted repairs instead of the full section payload.
    prompt_targets = _serialize_repair_targets(repair_targets)

    # Use the cleaned/collapsed errors from the targets for the prompt "Errors" section,
    # rather than the raw massive list.
    cleaned_prompt_errors = []
    for target in repair_targets:
      cleaned_prompt_errors.extend(target.errors)

    prompt_text = render_repair_prompt(request, section, prompt_targets, cleaned_prompt_errors)

    raw_schema = msgspec.json.schema(schema_response_cls)
    # Sanitize for Gemini (strips $defs, flattens refs, etc.)
    schema = self._schema_service.sanitize_schema(raw_schema, provider_name="gemini")

    purpose = f"repair_section_{section.section_number}_of_{request.depth}"
    call_index = f"{section.section_number}/{request.depth}"

    # Stamp the provider call with agent context for audit logging.
    with llm_call_context(agent=self.name, lesson_topic=request.topic, job_id=ctx.job_id, purpose=purpose, call_index=call_index):
      try:
        response = await self._model.generate_structured(prompt_text, schema)
      except Exception as exc:  # noqa: BLE001
        if not is_output_error(exc):
          raise
        # Retry the same request with the parser error appended.
        retry_prompt = self._build_json_retry_prompt(prompt_text=prompt_text, error=exc)
        retry_purpose = f"repair_section_retry_{section.section_number}_of_{request.depth}"
        retry_call_index = f"retry/{section.section_number}/{request.depth}"

        with llm_call_context(agent=self.name, lesson_topic=request.topic, job_id=ctx.job_id, purpose=retry_purpose, call_index=retry_call_index):
          response = await self._model.generate_structured(retry_prompt, schema)

        self._record_usage(agent=self.name, purpose=retry_purpose, call_index=retry_call_index, usage=response.usage)

    # Record usage after the primary structured call completes.
    self._record_usage(agent=self.name, purpose=purpose, call_index=call_index, usage=response.usage)

    result_dict = response.content
    # Convert dict to msgspec Struct to ensure it matches our internal model
    repair_response = msgspec.convert(result_dict, type=CanonicalRepairResponse)
    repaired_payload = _prune_none_values(msgspec.to_builtins(repair_response))

    # Apply only the repaired widget payloads back into their original positions.
    repaired_json = _apply_repairs(section_json, repaired_payload, repair_targets)
    validator = self._schema_service.validate_section_payload
    ok, repaired_errors, _ = validator(repaired_json, topic=topic, section_index=section_number)
    changes = ["ai_repair"]
    err_list = [] if ok else repaired_errors
    if not err_list:
      await _persist_repaired_section(section_id=persisted_section_id, repaired_json=repaired_json)
    return RepairResult(section_number=section_number, fixed_json=repaired_json, changes=changes, errors=err_list)


async def _persist_repaired_section(section_id: int | None, repaired_json: JsonDict) -> None:
  """Persist repaired section payload and canonical shorthand for the existing section row."""
  from app.services.section_shorthand import build_section_shorthand_content
  from app.storage.postgres_lessons_repo import PostgresLessonsRepository

  if section_id is None:
    raise RuntimeError("Repairer missing persisted section id for section update.")
  shorthand_content = build_section_shorthand_content(repaired_json)
  repo = PostgresLessonsRepository()
  await repo.update_section_content_and_shorthand(section_id, repaired_json, shorthand_content)


def _collect_repair_targets(section_json: JsonDict, errors: Errors) -> list[RepairTarget]:
  """Collect widget repair targets from validation errors."""
  errors_by_path: dict[str, list[str]] = {}

  # Normalize error strings into a per-widget bucket keyed by path.
  for path, message in _parse_error_entries(errors):
    target_path = _target_path_from_error(path)

    if target_path is None:
      continue

    if _is_subsection_path(target_path):
      # Expand subsection-level errors into item-level repair targets.
      expanded = _expand_subsection_targets(section_json, target_path, message)

      for item_path, item_messages in expanded.items():
        errors_by_path.setdefault(item_path, []).extend(item_messages)

      if expanded:
        continue

    errors_by_path.setdefault(target_path, []).append(message)

  targets: list[RepairTarget] = []

  # Resolve each target path into the actual widget payload to repair.
  for target_path, messages in errors_by_path.items():
    payload = _value_at_path(section_json, target_path)

    if payload is None:
      continue

    # Attempt to collapse massive union errors into a single actionable message.
    # This prevents the repair prompt from being flooded with "Field required" for every possible widget.
    cleaned_messages = _collapse_union_errors(messages, payload)

    normalized = _safe_normalize_widget(payload)

    if normalized is None:
      continue

    widget_type = _detect_widget_type(normalized)
    targets.append(RepairTarget(path=target_path, widget=normalized, errors=cleaned_messages, widget_type=widget_type))

  return targets


def _collapse_union_errors(errors: list[str], payload: Any) -> list[str]:
  """Filter noise when Pydantic reports validation failure against every Union member.

  If we see too many 'Field required' errors, it usually means the widget is malformed
  or unrecognized, and Pydantic tried to match it against all 20+ widget types.
  """
  # If the error list is small, it's likely specific and useful. Keep it.
  if len(errors) < 10:
    return errors

  # Check if the payload has a recognizable single key (typical for Dylen widgets).
  # If so, we can try to filter errors to only those relevant to that key.
  guessed_type = None
  if isinstance(payload, dict) and len(payload) == 1:
    guessed_type = next(iter(payload.keys()))

  if guessed_type:
    # Keep errors that mention the guessed type or are generic "Input should be..."
    relevant_errors = [e for e in errors if guessed_type in e or "Input should be" in e or "Field required" not in e]
    if relevant_errors:
      return relevant_errors

  # If we couldn't filter by type, and it's still a massive list, likely a formatting disaster.
  # Return a summary error.
  field_required_count = sum(1 for e in errors if "Field required" in e)
  if field_required_count > 5:
    return ["Invalid widget format: payload does not match any supported widget schema."]

  return errors


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


def _apply_subsection_fallbacks(section_json: JsonDict, errors: Errors) -> tuple[JsonDict, list[str]]:
  """Apply local subsection fixes based on error paths to avoid extra AI calls.

  Also proactively scans for 'misplaced subsections' (subsection blocks inside the 'items' list)
  and moves them to the 'subsections' list where they belong.
  """
  repaired = copy.deepcopy(section_json)
  changes: list[str] = []

  # 1. Detect and fix misplaced subsections (Subsections put inside 'items' list)
  # This happens when Structurer confuses section.items vs section.subsections.
  section_items = repaired.get("items")
  if isinstance(section_items, list) and section_items:
    new_items = []
    misplaced_subsections = []

    for item in section_items:
      # If an item looks like a SubsectionBlock (has legacy or canonical section key + items list),
      # it's likely misplaced.
      is_subsection_block = isinstance(item, dict) and (("title" in item or "subsection" in item or "section" in item) and isinstance(item.get("items"), list))

      if is_subsection_block:
        misplaced_subsections.append(item)
      else:
        new_items.append(item)

    if misplaced_subsections:
      # Move them to the main subsections list
      current_subsections = repaired.get("subsections", [])
      if not isinstance(current_subsections, list):
        current_subsections = []

      current_subsections.extend(misplaced_subsections)
      repaired["subsections"] = current_subsections
      repaired["items"] = new_items
      changes.append("moved_misplaced_subsections")

  # 2. Inspect validation errors for other subsection-level issues
  for path, _message in _parse_error_entries(errors):
    tokens = [token for token in path.split(".") if token]

    # Strip the lesson wrapper added during section validation.
    if len(tokens) >= 2 and tokens[0] == "blocks" and tokens[1].isdigit():
      tokens = tokens[2:]

    # Focus only on subsection-related errors.
    if len(tokens) < 2 or tokens[0] != "subsections" or not tokens[1].isdigit():
      continue

    subsection_index = int(tokens[1])
    subsection_path = f"subsections.{subsection_index}"
    subsection = _value_at_path(repaired, subsection_path)

    if not isinstance(subsection, dict):
      continue

    # Ensure canonical subsection key exists for schema validation.
    if len(tokens) >= 3 and tokens[2] in ("title", "subsection", "section"):
      section_name = subsection.get("section")
      if not isinstance(section_name, str) or not section_name.strip():
        migrated = False
        for legacy_key in ("title", "subsection"):
          legacy_value = subsection.pop(legacy_key, None)
          if isinstance(legacy_value, str) and legacy_value.strip():
            subsection["section"] = legacy_value
            changes.append(f"migrated_subsection_section_{subsection_index}")
            migrated = True
            break
        if not migrated:
          subsection["section"] = f"Subsection {subsection_index + 1}"
          changes.append(f"subsection_section_{subsection_index}")

      # Remove deprecated alias keys after migration.
      for legacy_key in ("title", "subsection"):
        if legacy_key in subsection:
          subsection.pop(legacy_key)
          changes.append(f"removed_deprecated_{legacy_key}_{subsection_index}")

    # Normalize subsection items into a list so downstream validation stays stable.
    if "items" not in subsection or not isinstance(subsection.get("items"), list):
      coerced_items = _coerce_items_list(subsection.get("items"))
      subsection["items"] = coerced_items
      changes.append(f"subsection_items_{subsection_index}")

  return repaired, changes


def _is_subsection_path(path: str) -> bool:
  """Identify subsection container paths so errors can be expanded into item repairs."""
  tokens = [token for token in path.split(".") if token]

  # Require the simple subsection.<index> shape to avoid misclassification.
  if len(tokens) != 2:
    return False

  return tokens[0] == "subsections" and tokens[1].isdigit()


def _expand_subsection_targets(section_json: JsonDict, path: str, message: str) -> dict[str, list[str]]:
  """Expand subsection errors into per-item targets to batch AI repairs."""
  expanded: dict[str, list[str]] = {}
  subsection = _value_at_path(section_json, path)

  # Guard against non-dict subsection payloads.
  if not isinstance(subsection, dict):
    return expanded

  items = subsection.get("items")

  # Guard against missing or malformed items lists.
  if not isinstance(items, list):
    return expanded

  # Emit item-level paths so widget repairs include subsection content.
  for item_index in range(len(items)):
    item_path = f"{path}.items.{item_index}"
    expanded[item_path] = [message]

  return expanded


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

  # Fallback to subsection-level targeting when items are not specified.
  if len(tokens) >= 2 and tokens[0] == "subsections" and tokens[1].isdigit():
    return ".".join(tokens[:2])

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


def _coerce_items_list(value: Any) -> list[Any]:
  """Coerce malformed subsection items into a safe list for repair reuse."""
  # Preserve valid lists to avoid reshaping already-correct items.
  if isinstance(value, list):
    return value

  # Wrap single widget mappings so subsection items remain iterable.
  if isinstance(value, dict):
    return [value]

  # Parse string payloads when they look like JSON, otherwise fallback to MarkdownText.
  if isinstance(value, str):
    stripped = value.strip()

    if not stripped:
      return []

    if stripped.startswith("[") or stripped.startswith("{"):
      try:
        parsed = parse_json_with_fallback(stripped)
      except json.JSONDecodeError:
        parsed = None

      if isinstance(parsed, list):
        return parsed

      if isinstance(parsed, dict):
        return [parsed]

    return [{"markdown": {"markdown": stripped}}]

  # Fallback to MarkdownText for scalar values to preserve context.
  if value is None:
    return []

  return [{"markdown": {"markdown": str(value)}}]


def _detect_widget_type(widget: Any) -> str | None:
  """Infer a widget type label from a widget payload."""
  # Prefer shorthand keys so repair schemas stay aligned with the engine format.
  if isinstance(widget, dict):
    if len(widget) == 1:
      return str(next(iter(widget.keys())))
    if "type" in widget:
      other_keys = [key for key in widget.keys() if key != "type"]
      if len(other_keys) == 1:
        return str(other_keys[0])
      return str(widget["type"])
  if isinstance(widget, str):
    return "markdown"
  return None


def _safe_normalize_widget(widget: Any) -> JsonDict | None:
  """Normalize a widget payload to full form, preserving raw data on failure."""

  # Normalize shorthand into explicit widget objects for schema validation.
  if isinstance(widget, dict):
    return widget

  if isinstance(widget, str):
    return {"markdown": {"markdown": widget}}

  return None


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
