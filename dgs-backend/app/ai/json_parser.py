"""Lenient JSON parsing helpers for LLM outputs."""

from __future__ import annotations

import json
import re
from typing import Any

_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def parse_json_with_fallback(raw: str) -> Any:
  """Parse JSON with minimal recovery to keep LLM retries low."""
  last_error: json.JSONDecodeError | None = None

  # Prefer strict parsing so valid JSON is preserved without mutation.
  try:
    return json.loads(raw)
  except json.JSONDecodeError as exc:
    last_error = exc

  # Extract the first JSON object/array to ignore leading or trailing text.
  candidate = _extract_json_block(raw)

  # Fail fast when no JSON-shaped payload is present in the response.
  if candidate is None:

    if last_error is None:
      raise json.JSONDecodeError("Invalid JSON payload", raw, 0)

    raise last_error

  # Retry strict parsing on the extracted candidate before modifying it.
  try:
    return json.loads(candidate)
  except json.JSONDecodeError as exc:
    last_error = exc

  # Strip trailing commas that commonly appear in LLM output.
  cleaned = _strip_trailing_commas(candidate)

  # Parse after cleanup, letting JSON errors propagate when still invalid.
  return json.loads(cleaned)


def _extract_json_block(raw: str) -> str | None:
  """Locate the first balanced JSON object/array for recovery parsing."""
  start_index: int | None = None
  depth = 0
  in_string = False
  escape = False

  # Scan the text for a balanced JSON payload while honoring string escapes.
  for index, char in enumerate(raw):

    if start_index is None:

      if char in "{[":
        start_index = index
        depth = 1

      continue

    if in_string:

      if escape:
        escape = False
        continue

      if char == "\\":
        escape = True
        continue

      if char == '"':
        in_string = False

      continue

    if char == '"':
      in_string = True
      continue

    if char in "{[":
      depth += 1
      continue

    if char in "}]":
      depth -= 1

      if depth == 0:
        return raw[start_index : index + 1]

  return None


def _strip_trailing_commas(raw: str) -> str:
  """Remove trailing commas before closing brackets for lenient parsing."""
  # Keep the transform narrow so only obvious comma violations are altered.
  return _TRAILING_COMMA_RE.sub(r"\1", raw)
