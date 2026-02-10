"""Shared section shorthand conversion helpers."""

from __future__ import annotations

from typing import Any

import msgspec
from app.schema.section_normalizer import normalize_section_payload_keys
from app.schema.widget_models import Section as CanonicalSection


def build_section_shorthand_content(section_json: dict[str, Any]) -> dict[str, Any]:
  """Build canonical shorthand output for frontend section retrieval."""
  if not isinstance(section_json, dict):
    raise RuntimeError("Section shorthand conversion requires a JSON object payload.")
  try:
    normalized_section_json = normalize_section_payload_keys(section_json)
    section_struct = msgspec.convert(normalized_section_json, type=CanonicalSection)
    return section_struct.output()
  except Exception as exc:  # noqa: BLE001
    raise RuntimeError(f"Unable to convert section payload to shorthand via canonical path. error={exc}") from exc
