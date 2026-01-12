"""Unit tests for WidgetRegistry."""

from pathlib import Path

import pytest

from app.schema.widgets_loader import load_widget_registry


def test_load_widget_registry() -> None:
    """Test that we can load the widget registry from widgets_prompt.md."""
    widgets_path = Path(__file__).parents[2] / "dgs-backend" / "app" / "schema" / "widgets_prompt.md"
    registry = load_widget_registry(widgets_path)

    # Verify known widgets are loaded
    assert registry.is_known("p")
    assert registry.is_known("flip")
    assert registry.is_known("mcqs")
    assert registry.is_known("table")
    assert registry.is_known("interactiveTerminal")
    assert registry.is_known("terminalDemo")
    
    # Verify unknown widgets return False
    assert not registry.is_known("unknown_widget")


def test_widget_definition_fields() -> None:
    """Test that widget definitions include field information."""
    widgets_path = Path(__file__).parents[2] / "dgs-backend" / "app" / "schema" / "widgets_prompt.md"
    registry = load_widget_registry(widgets_path)

    # Check that shorthand widgets are correctly identified
    flip_def = registry.get_definition("flip")
    assert flip_def is not None
    assert flip_def.is_shorthand

    # Check that we extracted shorthand positions for some widgets
    free_text_def = registry.get_definition("freeText")
    if free_text_def and free_text_def.is_shorthand:
        assert len(free_text_def.shorthand_positions) > 0
