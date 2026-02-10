"""Unit tests for schema sanitization behavior."""

from __future__ import annotations

from app.schema.service import SchemaService


def test_sanitize_schema_preserves_max_length_and_max_items() -> None:
  """Keep max bounds in sanitized schema so Gemini receives length limits."""
  service = SchemaService()
  raw_schema = {"type": "object", "properties": {"title": {"type": "string", "maxLength": 40, "minLength": 1}, "items": {"type": "array", "maxItems": 5, "minItems": 1, "items": {"type": "string", "maxLength": 20}}}, "required": ["title", "items"]}
  sanitized = service.sanitize_schema(raw_schema, provider_name="gemini")
  title_schema = sanitized["properties"]["title"]
  items_schema = sanitized["properties"]["items"]
  assert title_schema["maxLength"] == 40
  assert "minLength" not in title_schema
  assert items_schema["maxItems"] == 5
  assert "minItems" not in items_schema
  assert items_schema["items"]["maxLength"] == 20
