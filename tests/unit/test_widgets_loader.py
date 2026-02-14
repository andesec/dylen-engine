"""Unit tests for WidgetRegistry."""

from pathlib import Path

from app.schema.widgets_loader import load_widget_registry


def test_load_widget_registry() -> None:
  """Test that we can load the widget registry from widgets_prompt.md."""
  widgets_path = Path(__file__).parents[2] / "app" / "schema" / "widgets_prompt.md"
  registry = load_widget_registry(widgets_path)

  # Verify known widgets are loaded
  assert registry.is_known("markdown")
  assert registry.is_known("flipcards")
  assert registry.is_known("mcqs")
  assert registry.is_known("table")
  assert registry.is_known("interactiveTerminal")
  assert registry.is_known("terminalDemo")
  assert not registry.is_known("p")
  assert not registry.is_known("ul")
  assert not registry.is_known("ol")

  # Verify unknown widgets return False
  assert not registry.is_known("unknown_widget")


def test_widget_definition_fields() -> None:
  """Test that widget definitions include field information."""
  widgets_path = Path(__file__).parents[2] / "app" / "schema" / "widgets_prompt.md"
  registry = load_widget_registry(widgets_path)

  # Check that shorthand widgets are correctly identified (all current widgets use shorthand array syntax)
  flip_def = registry.get_definition("flipcards")
  assert flip_def is not None
  assert flip_def.is_shorthand  # flipcards uses array syntax

  # Check that we extracted fields for widgets with numbered rules
  free_text_def = registry.get_definition("freeText")
  assert free_text_def is not None
  # freeText has numbered rules, so fields should be extracted
  assert len(free_text_def.fields) > 0 or len(free_text_def.shorthand_positions) > 0
