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
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        last_error = exc

    # Quote unquoted object keys to recover from JS-style output.
    quoted = _quote_unquoted_keys(cleaned)

    # Parse after quoting, letting JSON errors propagate when still invalid.
    try:
        return json.loads(quoted)
    except json.JSONDecodeError as exc:
        last_error = exc

    # Insert missing commas between values inside arrays/objects.
    repaired = _insert_missing_commas(quoted)

    # Parse after repairing, letting JSON errors propagate when still invalid.
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as exc:
        last_error = exc

    # Raise the last error when none of the recovery passes succeed.
    raise last_error


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


def _quote_unquoted_keys(raw: str) -> str:
    """Wrap bare object keys in quotes to handle JS-style output."""
    output: list[str] = []
    in_string = False
    escape = False
    expecting_key = False
    index = 0

    # Walk the payload and only transform keys outside of strings.
    while index < len(raw):
        char = raw[index]

        if in_string:
            # Preserve escaped characters while inside string literals.
            if escape:
                output.append(char)
                escape = False
                index += 1
                continue

            if char == "\\":
                output.append(char)
                escape = True
                index += 1
                continue

            if char == '"':
                output.append(char)
                in_string = False
                index += 1
                continue

            output.append(char)
            index += 1
            continue

        if char == '"':
            output.append(char)
            in_string = True
            index += 1
            continue

        if char == "{":
            output.append(char)
            expecting_key = True
            index += 1
            continue

        if char == "}":
            output.append(char)
            expecting_key = False
            index += 1
            continue

        if char == ",":
            output.append(char)
            expecting_key = True
            index += 1
            continue

        if char == ":":
            output.append(char)
            expecting_key = False
            index += 1
            continue

        if not expecting_key:
            output.append(char)
            index += 1
            continue

        # Preserve whitespace while we are waiting for a key token.
        if char.isspace():
            output.append(char)
            index += 1
            continue

        # Leave quoted keys untouched.
        if char in "\"'":
            output.append(char)
            in_string = char == '"'
            index += 1
            continue

        # Quote bare keys that look like identifiers and precede a colon.
        if char.isalpha() or char == "_":
            start = index
            index += 1

            # Consume identifier characters in the key.
            while index < len(raw) and (raw[index].isalnum() or raw[index] in "_-"):
                index += 1

            key = raw[start:index]
            probe = index

            # Capture whitespace between key and colon.
            while probe < len(raw) and raw[probe].isspace():
                probe += 1

            if probe < len(raw) and raw[probe] == ":":
                output.append(f'"{key}"')
                output.append(raw[index:probe])
                output.append(":")
                expecting_key = False
                index = probe + 1
                continue

            output.append(key)
            continue

        output.append(char)
        index += 1

    return "".join(output)


def _insert_missing_commas(raw: str) -> str:
    """Insert commas when values run together to salvage near-JSON outputs."""
    output: list[str] = []
    in_string = False
    escape = False
    expecting_key = False
    expecting_value = False
    last_value_end = False
    last_non_space = ""
    stack: list[str] = []
    index = 0

    # Walk characters while tracking structural context and string boundaries.
    while index < len(raw):
        char = raw[index]

        # Preserve characters inside strings verbatim while tracking escapes.
        if in_string:
            if escape:
                output.append(char)
                escape = False
                index += 1
                continue

            if char == "\\":
                output.append(char)
                escape = True
                index += 1
                continue

            if char == '"':
                output.append(char)
                in_string = False

                if expecting_key:
                    expecting_key = False
                elif expecting_value:
                    expecting_value = False
                    last_value_end = True

                index += 1
                continue

            output.append(char)
            index += 1
            continue

        # Insert missing commas before new values within arrays/objects.
        if not char.isspace() and last_value_end and stack and last_non_space not in "{[,:":
            container = stack[-1]

            if container == "object" and char == '"':
                output.append(",")
                expecting_key = True
                last_value_end = False
                last_non_space = ","

            if container == "array" and _is_value_start(char):
                output.append(",")
                expecting_value = True
                last_value_end = False
                last_non_space = ","

        # Track string starts.
        if char == '"':
            output.append(char)
            in_string = True
            last_non_space = '"'
            index += 1
            continue

        # Track container entry for objects.
        if char == "{":
            output.append(char)
            stack.append("object")
            expecting_key = True
            expecting_value = False
            last_value_end = False
            last_non_space = "{"
            index += 1
            continue

        # Track container entry for arrays.
        if char == "[":
            output.append(char)
            stack.append("array")
            expecting_key = False
            expecting_value = True
            last_value_end = False
            last_non_space = "["
            index += 1
            continue

        # Track container exit for objects.
        if char == "}":
            output.append(char)

            if stack:
                stack.pop()

            expecting_key = False
            expecting_value = False
            last_value_end = True
            last_non_space = "}"
            index += 1
            continue

        # Track container exit for arrays.
        if char == "]":
            output.append(char)

            if stack:
                stack.pop()

            expecting_key = False
            expecting_value = False
            last_value_end = True
            last_non_space = "]"
            index += 1
            continue

        # Track commas that already separate elements.
        if char == ",":
            output.append(char)
            last_value_end = False

            # Reset context so the next token is parsed in the right container.
            if stack:
                container = stack[-1]

                if container == "object":
                    expecting_key = True
                    expecting_value = False

                if container == "array":
                    expecting_key = False
                    expecting_value = True

            last_non_space = ","
            index += 1
            continue

        # Track colons that separate keys from values.
        if char == ":":
            output.append(char)
            expecting_key = False
            expecting_value = True
            last_value_end = False
            last_non_space = ":"
            index += 1
            continue

        # Consume literal/number tokens as whole values for delimiter detection.
        if expecting_value and _is_value_start(char):
            start = index
            index += 1

            while index < len(raw) and raw[index] not in " \t\r\n,]}":
                index += 1

            output.append(raw[start:index])
            expecting_value = False
            last_value_end = True
            last_non_space = output[-1][-1]
            continue

        # Preserve other characters as-is.
        output.append(char)
        if not char.isspace():
            last_non_space = char
        index += 1

    return "".join(output)


def _is_value_start(char: str) -> bool:
    """Identify token starts so missing commas are inserted safely."""
    if char in '"{[':
        return True

    if char.isdigit() or char == "-":
        return True

    return char in {"t", "f", "n"}
