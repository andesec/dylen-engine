"""Unit tests for API exception sanitization behavior."""

from __future__ import annotations

from app.core.exceptions import _sanitize_validation_errors


def test_sanitize_validation_errors_removes_input_and_serializes_exception_ctx() -> None:
  """Ensure validation errors stay JSON-serializable and redact raw request payloads."""
  errors = [{"type": "value_error", "loc": ("body",), "msg": "Value error, Unsupported widget id 'ul'.", "input": {"widgets": ["ul", "p"]}, "ctx": {"error": ValueError("Unsupported widget id 'ul'."), "input": {"widgets": ["ul", "p"]}}}]
  sanitized = _sanitize_validation_errors(errors)
  assert "input" not in sanitized[0]
  assert sanitized[0]["ctx"]["error"] == "ValueError: Unsupported widget id 'ul'."
  assert "input" not in sanitized[0]["ctx"]
