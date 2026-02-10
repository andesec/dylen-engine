"""
Test schema generation utilities.

Run with: python3 test_schema_gen.py
"""

import json

from app.schema.schema_builder import build_schema_for_context
from app.schema.schema_export import struct_to_json_schema
from app.schema.widget_models import FlipPayload, InteractiveTerminalPayload, SwipeCardsPayload


def test_tuple_schema():
  """Test that tuple types generate prefixItems."""
  print("\n=== Testing Tuple Schema Generation ===")

  # Test InteractiveTerminalPayload with tuple[str, str, str]
  terminal_schema = struct_to_json_schema(InteractiveTerminalPayload)
  print("\nInteractiveTerminalPayload schema:")
  print(json.dumps(terminal_schema, indent=2))

  # Verify rules uses prefixItems
  rules_schema = terminal_schema["properties"]["rules"]
  assert rules_schema["type"] == "array", "Rules should be array type"
  assert "items" in rules_schema, "Rules should have items"
  assert rules_schema["items"]["type"] == "array", "Rules items should be array"
  assert "prefixItems" in rules_schema["items"], "Rules should use prefixItems for tuples"
  assert len(rules_schema["items"]["prefixItems"]) == 3, "Should have 3 tuple elements"
  print("✓ Terminal rules correctly uses prefixItems for tuple[str, str, str]")


def test_swipe_cards_tuple():
  """Test that SwipeCardsPayload.buckets uses tuple[str, str]."""
  print("\n=== Testing SwipeCards Buckets Tuple ===")

  swipe_schema = struct_to_json_schema(SwipeCardsPayload)
  print("\nSwipeCardsPayload schema:")
  print(json.dumps(swipe_schema, indent=2))

  buckets_schema = swipe_schema["properties"]["buckets"]
  assert buckets_schema["type"] == "array", "Buckets should be array type"
  assert "prefixItems" in buckets_schema, "Buckets should use prefixItems for tuple"
  assert len(buckets_schema["prefixItems"]) == 2, "Should have 2 bucket labels"
  print("✓ Buckets correctly uses prefixItems for tuple[str, str]")


def test_meta_constraints():
  """Test that msgspec.Meta constraints are extracted."""
  print("\n=== Testing Meta Constraints ===")

  flip_schema = struct_to_json_schema(FlipPayload)
  print("\nFlipPayload schema:")
  print(json.dumps(flip_schema, indent=2))

  front_schema = flip_schema["properties"]["front"]
  assert "maxLength" in front_schema, "Front should have maxLength"
  assert front_schema["maxLength"] == 80, "Front maxLength should be 80"
  assert "description" in front_schema, "Front should have description"
  print("✓ Meta constraints correctly extracted")


def test_context_schemas():
  """Test building schemas for different contexts."""
  print("\n=== Testing Context Schemas ===")

  # Test outcomes context (minimal)
  outcomes_config = build_schema_for_context("outcomes")
  print("\nOutcomes context config:")
  print(f"MIME type: {outcomes_config['response_mime_type']}")
  print(f"Schema keys: {list(outcomes_config['response_json_schema'].keys())}")
  print(f"Definitions: {list(outcomes_config['response_json_schema'].get('$defs', {}).keys())}")

  # Test section_builder context (medium)
  section_config = build_schema_for_context("section_builder")
  print("\nSection builder context config:")
  print(f"Definitions: {list(section_config['response_json_schema'].get('$defs', {}).keys())}")

  # Verify outcomes has fewer definitions than section_builder
  outcomes_defs = len(outcomes_config["response_json_schema"].get("$defs", {}))
  section_defs = len(section_config["response_json_schema"].get("$defs", {}))
  print(f"\nOutcomes definitions: {outcomes_defs}")
  print(f"Section builder definitions: {section_defs}")
  assert outcomes_defs < section_defs, "Outcomes should have fewer definitions"
  print("✓ Context-based schema generation works correctly")


def test_token_optimization():
  """Compare token counts for different schema approaches."""
  print("\n=== Testing Token Optimization ===")

  # Full schema
  full_config = build_schema_for_context("full")
  full_json = json.dumps(full_config["response_json_schema"])

  # Minimal schema (outcomes)
  minimal_config = build_schema_for_context("outcomes")
  minimal_json = json.dumps(minimal_config["response_json_schema"])

  print(f"\nFull schema size: {len(full_json)} characters")
  print(f"Minimal schema size: {len(minimal_json)} characters")
  print(f"Reduction: {100 * (1 - len(minimal_json) / len(full_json)):.1f}%")

  assert len(minimal_json) < len(full_json), "Minimal schema should be smaller"
  print("✓ Token optimization working as expected")


if __name__ == "__main__":
  print("Running Schema Generation Tests...")

  try:
    test_tuple_schema()
    test_swipe_cards_tuple()
    test_meta_constraints()
    test_context_schemas()
    test_token_optimization()

    print("\n" + "=" * 50)
    print("✅ All tests passed!")
    print("=" * 50)
  except AssertionError as e:
    print(f"\n❌ Test failed: {e}")
    raise
  except Exception as e:
    print(f"\n❌ Error: {e}")
    raise
