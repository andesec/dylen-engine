"""Section payload key normalization helpers."""

from __future__ import annotations

import copy
from typing import Any


def normalize_lesson_section_keys(payload: Any) -> Any:
  """Normalize legacy section/subsection title keys to canonical `section` keys."""
  normalized = copy.deepcopy(payload)
  if not isinstance(normalized, dict):
    return normalized
  blocks = normalized.get("blocks")
  if not isinstance(blocks, list):
    return normalized
  normalized["blocks"] = [_normalize_section_block(block) for block in blocks]
  return normalized


def normalize_section_payload_keys(section_payload: Any) -> Any:
  """Normalize one section payload to canonical `section` keys."""
  return _normalize_section_block(copy.deepcopy(section_payload))


def _normalize_section_block(section_payload: Any) -> Any:
  if not isinstance(section_payload, dict):
    return section_payload
  if "section" not in section_payload and isinstance(section_payload.get("title"), str):
    section_payload["section"] = str(section_payload.get("title"))
  subsection_payloads = section_payload.get("subsections")
  if isinstance(subsection_payloads, list):
    section_payload["subsections"] = [_normalize_subsection_block(item) for item in subsection_payloads]
  return section_payload


def _normalize_subsection_block(subsection_payload: Any) -> Any:
  if not isinstance(subsection_payload, dict):
    return subsection_payload
  if "section" not in subsection_payload:
    if isinstance(subsection_payload.get("title"), str):
      subsection_payload["section"] = str(subsection_payload.get("title"))
    elif isinstance(subsection_payload.get("subsection"), str):
      subsection_payload["section"] = str(subsection_payload.get("subsection"))
  return subsection_payload
