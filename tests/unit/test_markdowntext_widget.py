"""Unit tests for the MarkdownText widget cutover."""

from __future__ import annotations

import json

from app.schema.service import SchemaService
from app.schema.validate_lesson import validate_lesson


def test_markdowntext_accepts_object() -> None:
  """Accept {"markdown": {"markdown": "...", "align": "..."}} object/struct widget payloads."""
  service = SchemaService()
  payload = {
    "title": "Lesson Title",
    "blocks": [
      {
        "title": "Section Title",
        "markdown": {"markdown": "Section Intro must be thirty characters long"},
        "subsections": [
          {
            "title": "Subsection Title",
            "items": [
              {"markdown": {"markdown": "Hello this is a long enough string to pass validation."}},
              {"markdown": {"markdown": "Centered text that is long enough.", "align": "center"}},
              {"markdown": {"markdown": "Left aligned text that is long enough.", "align": "left"}},
            ],
          }
        ],
      }
    ],
  }
  result = service.validate_lesson_payload(payload)
  if not result.ok:
    print(f"\nValidation failed: {result.issues}")
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
    {"title": "T", "blocks": [{"title": "S", "markdown": {"markdown": "I"}, "subsections": [{"title": "Sub", "items": [{"markdown": ["Array Not Allowed"]}]}]}]},
    {"title": "T", "blocks": [{"title": "S", "markdown": {"markdown": "I"}, "subsections": [{"title": "Sub", "items": [{"markdown": "String Not Allowed"}]}]}]},
  ]
  for payload in legacy_payloads:
    result = service.validate_lesson_payload(payload)
    assert not result.ok


def test_markdowntext_newlines_are_standard_json_escaped() -> None:
  """Ensure JSON serialization escapes newlines using standard JSON escaping."""
  widget = {"markdown": {"markdown": "Line 1\nLine 2"}}
  encoded = json.dumps(widget)
  assert "\\n" in encoded
  assert "Line 1\nLine 2" not in encoded


def test_markdowntext_enforces_max_length() -> None:
  """Reject MarkdownText widgets when md exceeds the configured hard limit."""
  # Use max=40 to respect schema min=30
  long_text = "0123456789" * 5  # 50 chars
  payload = {"title": "Lesson Title", "blocks": [{"title": "Section Title", "markdown": {"markdown": "Section Intro must be thirty characters long"}, "subsections": [{"title": "Subsection Title", "items": [{"markdown": {"markdown": long_text}}]}]}]}
  ok, errors, _model = validate_lesson(payload, max_markdown_chars=40)
  assert not ok
  assert any("markdown exceeds max length" in error for error in errors)


def test_markdowntext_allows_within_max_length() -> None:
  """Accept MarkdownText widgets when md is within the configured hard limit."""
  # Use max=40 to respect schema min=30
  short_text = "0123456789" * 3 + "abcde"  # 35 chars
  payload = {"title": "Lesson Title", "blocks": [{"title": "Section Title", "markdown": {"markdown": "Section Intro must be thirty characters long"}, "subsections": [{"title": "Subsection Title", "items": [{"markdown": {"markdown": short_text}}]}]}]}
  ok, errors, _model = validate_lesson(payload, max_markdown_chars=40)
  assert ok
  assert errors == []
