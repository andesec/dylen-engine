"""Shared section shorthand conversion helpers."""

from __future__ import annotations

import copy
import logging
from typing import Any, cast

import msgspec
from app.schema.lesson_models import LessonDocument
from app.schema.serialize_lesson import lesson_to_shorthand
from app.schema.widget_models import Section as CanonicalSection
from app.schema.widget_models import get_widget_payload, resolve_widget_shorthand_name

logger = logging.getLogger(__name__)


def _get_known_widget_keys(widget_item: dict[str, Any], *, include_null_values: bool) -> list[str]:
  """Return recognized widget keys, optionally including keys with null values."""
  widget_keys: list[str] = []
  for key, value in widget_item.items():
    try:
      resolve_widget_shorthand_name(key)
    except Exception:  # noqa: BLE001
      continue

    # Null payloads should not win key selection during shorthand normalization.
    if value is None and not include_null_values:
      continue
    widget_keys.append(key)
  return widget_keys


def _coerce_markdown_to_shorthand(value: Any) -> list[str]:
  """Normalize markdown payloads into shorthand `[markdown, align?]` arrays."""
  if isinstance(value, list):
    return [str(item) for item in value]
  if isinstance(value, str):
    return [value]
  if isinstance(value, dict):
    markdown_value = value.get("markdown")
    align_value = value.get("align")
    markdown_text = markdown_value if isinstance(markdown_value, str) else str(markdown_value or "")
    result = [markdown_text]
    if isinstance(align_value, str) and align_value in ("left", "center"):
      result.append(align_value)
    return result
  return [str(value)]


def _coerce_widget_item_to_shorthand(widget_item: Any) -> dict[str, Any]:
  """Normalize one widget item into canonical shorthand key/value shape."""
  if isinstance(widget_item, str):
    return {"markdown": [widget_item]}
  if not isinstance(widget_item, dict):
    raise ValueError("Widget item must be a JSON object or string.")

  # Prefer known keys with concrete payloads; null-only items are filtered at list level.
  widget_keys = _get_known_widget_keys(widget_item, include_null_values=False)
  if not widget_keys:
    raise ValueError("Widget item does not include a known widget key.")
  if len(widget_keys) > 1:
    logger.warning("Widget item has multiple widget keys %s; using the first one for shorthand conversion.", widget_keys)
  selected_key = widget_keys[0]
  selected_shorthand = resolve_widget_shorthand_name(selected_key)
  selected_value = widget_item.get(selected_key)
  if selected_shorthand == "markdown":
    return {"markdown": _coerce_markdown_to_shorthand(selected_value)}
  if isinstance(selected_value, list):
    return {selected_shorthand: selected_value}
  if isinstance(selected_value, dict):
    payload_type = get_widget_payload(selected_key)
    payload_struct = msgspec.convert(selected_value, type=payload_type)
    payload_output = payload_struct.output() if hasattr(payload_struct, "output") else msgspec.to_builtins(payload_struct)
    return {selected_shorthand: payload_output}
  return {selected_shorthand: selected_value}


def _coerce_items_list(items: Any) -> list[dict[str, Any]]:
  """Normalize raw `items` payloads into shorthand widget dicts."""
  if not isinstance(items, list):
    return []
  normalized_items: list[dict[str, Any]] = []
  for item in items:
    if isinstance(item, dict):
      # Drop entries like {"flip": null, "mcqs": null} before shorthand conversion.
      non_null_widget_keys = _get_known_widget_keys(item, include_null_values=False)
      null_widget_keys = _get_known_widget_keys(item, include_null_values=True)
      if null_widget_keys and not non_null_widget_keys:
        logger.warning("Skipping widget item with only null payloads for keys %s.", null_widget_keys)
        continue
    normalized_items.append(_coerce_widget_item_to_shorthand(item))
  return normalized_items


def _normalize_section_for_legacy_shorthand(section_json: dict[str, Any]) -> dict[str, Any]:
  """Prepare canonical/raw section payloads for legacy shorthand validation."""
  normalized = copy.deepcopy(section_json)
  if "section" not in normalized and isinstance(normalized.get("title"), str):
    normalized["section"] = normalized["title"]
  items = _coerce_items_list(normalized.get("items"))
  if "markdown" in normalized and normalized.get("markdown") is not None:
    items = [*items, {"markdown": _coerce_markdown_to_shorthand(normalized.get("markdown"))}]
  normalized["items"] = items
  subsections = normalized.get("subsections")
  if not isinstance(subsections, list):
    normalized["subsections"] = []
    return normalized
  normalized_subsections: list[dict[str, Any]] = []
  for subsection in subsections:
    if not isinstance(subsection, dict):
      continue
    subsection_copy = copy.deepcopy(subsection)
    if "subsection" not in subsection_copy and "section" not in subsection_copy and isinstance(subsection_copy.get("title"), str):
      subsection_copy["subsection"] = subsection_copy["title"]
    subsection_items = _coerce_items_list(subsection_copy.get("items"))
    if "markdown" in subsection_copy and subsection_copy.get("markdown") is not None:
      subsection_items = [*subsection_items, {"markdown": _coerce_markdown_to_shorthand(subsection_copy.get("markdown"))}]
    if not subsection_items:
      logger.warning("Skipping subsection without remaining widget items after normalization.")
      continue
    subsection_copy["items"] = subsection_items
    normalized_subsections.append(subsection_copy)
  normalized["subsections"] = normalized_subsections
  return normalized


def _build_legacy_shorthand(section_json: dict[str, Any]) -> dict[str, Any]:
  """Build shorthand using the legacy lesson serialization path."""
  normalized_section = _normalize_section_for_legacy_shorthand(section_json)
  lesson_title = str(normalized_section.get("section") or normalized_section.get("title") or "Section")
  payload = {"title": lesson_title, "blocks": [normalized_section]}
  lesson_model = LessonDocument.model_validate(payload)
  shorthand_lesson = lesson_to_shorthand(lesson_model)
  blocks = shorthand_lesson.get("blocks")
  if not isinstance(blocks, list) or not blocks or not isinstance(blocks[0], dict):
    raise RuntimeError("Legacy shorthand serializer returned an invalid section block payload.")
  return cast(dict[str, Any], blocks[0])


def build_section_shorthand_content(section_json: dict[str, Any]) -> dict[str, Any]:
  """
  Build canonical shorthand output for frontend section retrieval.

  How:
  1. Use the canonical `widget_models.Section.output()` path first.
  2. Fall back to the legacy shorthand validator/serializer path when stored payloads are shorthand-like.
  """
  if not isinstance(section_json, dict):
    raise RuntimeError("Section shorthand conversion requires a JSON object payload.")
  try:
    section_struct = msgspec.convert(section_json, type=CanonicalSection)
    return section_struct.output()
  except Exception as canonical_exc:  # noqa: BLE001
    try:
      return _build_legacy_shorthand(section_json)
    except Exception as legacy_exc:  # noqa: BLE001
      raise RuntimeError(f"Unable to convert section payload to shorthand via canonical or legacy paths. canonical_error={canonical_exc} legacy_error={legacy_exc}") from legacy_exc
