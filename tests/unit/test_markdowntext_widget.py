"""Unit tests for the MarkdownText widget cutover."""

from __future__ import annotations

import json

from app.schema.service import SchemaService
from app.schema.validate_lesson import validate_lesson


def test_markdowntext_accepts_shorthand() -> None:
  """Accept {"markdown":[md, align?]} shorthand widget payloads."""
  service = SchemaService()
  payload = {"title": "T", "blocks": [{"section": "S", "items": [{"markdown": ["Hello"]}, {"markdown": ["Centered", "center"]}, {"markdown": ["Left", "left"]}], "subsections": []}]}
  result = service.validate_lesson_payload(payload)
  assert result.ok


def test_markdowntext_rejects_legacy_widgets() -> None:
  """Reject removed widget types and legacy shorthands."""
  service = SchemaService()
  legacy_payloads = [
    {"title": "T", "blocks": [{"section": "S", "items": ["Legacy paragraph string"], "subsections": []}]},
    {"title": "T", "blocks": [{"section": "S", "items": [{"p": "Legacy paragraph"}], "subsections": []}]},
    {"title": "T", "blocks": [{"section": "S", "items": [{"paragraph": "Legacy paragraph"}], "subsections": []}]},
    {"title": "T", "blocks": [{"section": "S", "items": [{"callouts": "Legacy callout"}], "subsections": []}]},
    {"title": "T", "blocks": [{"section": "S", "items": [{"warn": "Legacy warn"}], "subsections": []}]},
    {"title": "T", "blocks": [{"section": "S", "items": [{"success": "Legacy success"}], "subsections": []}]},
    {"title": "T", "blocks": [{"section": "S", "items": [{"ul": ["a", "b"]}], "subsections": []}]},
    {"title": "T", "blocks": [{"section": "S", "items": [{"ol": ["a", "b"]}], "subsections": []}]},
    {"title": "T", "blocks": [{"section": "S", "items": [{"markdown": "Not shorthand"}], "subsections": []}]},
    {"title": "T", "blocks": [{"section": "S", "items": [{"markdown": {"md": "Not shorthand"}}], "subsections": []}]},
  ]
  for payload in legacy_payloads:
    result = service.validate_lesson_payload(payload)
    assert not result.ok


def test_markdowntext_newlines_are_standard_json_escaped() -> None:
  """Ensure JSON serialization escapes newlines using standard JSON escaping."""
  widget = {"markdown": ["Line 1\nLine 2"]}
  encoded = json.dumps(widget)
  assert "\\n" in encoded
  assert "Line 1\nLine 2" not in encoded


def test_markdowntext_enforces_max_length() -> None:
  """Reject MarkdownText widgets when md exceeds the configured hard limit."""
  payload = {"title": "T", "blocks": [{"section": "S", "items": [{"markdown": ["01234567890"]}], "subsections": []}]}
  ok, errors, _model = validate_lesson(payload, max_markdown_chars=10)
  assert not ok
  assert any("markdown exceeds max length" in error for error in errors)


def test_markdowntext_allows_within_max_length() -> None:
  """Accept MarkdownText widgets when md is within the configured hard limit."""
  payload = {"title": "T", "blocks": [{"section": "S", "items": [{"markdown": ["0123456789"]}], "subsections": []}]}
  ok, errors, _model = validate_lesson(payload, max_markdown_chars=10)
  assert ok
  assert errors == []
