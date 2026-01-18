"""Utilities for parsing vendored widget documentation into a registry."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WidgetFieldInfo:
  """Field information for a widget."""

  name: str
  required: bool = True
  field_type: str = "any"  # any, string, integer, boolean, array, object


@dataclass(frozen=True)
class WidgetDefinition:
  """Record describing a supported widget with field constraints."""

  name: str
  description: str
  fields: list[WidgetFieldInfo] = field(default_factory=list)
  is_shorthand: bool = False  # True if widget uses shorthand array syntax
  shorthand_positions: dict[int, str] = field(default_factory=dict)  # position -> field name


class WidgetRegistry:
  """Registry of widget definitions parsed from documentation."""

  def __init__(self, definitions: dict[str, WidgetDefinition]) -> None:
    self._definitions = definitions

  def is_known(self, widget_type: str) -> bool:
    """Return True if the widget type is defined."""
    return widget_type in self._definitions

  def describe(self, widget_type: str) -> str:
    """Return the description for a widget type."""
    return self._definitions[widget_type].description

  def available_types(self) -> list[str]:
    """List all available widget identifiers."""
    return sorted(self._definitions)

  def get_definition(self, widget_type: str) -> WidgetDefinition | None:
    """Get the full definition for a widget type."""
    return self._definitions.get(widget_type)


def _iter_widget_sections(lines: Iterable[str]) -> dict[str, str]:
  """Extract widget sections from markdown."""
  sections: dict[str, list[str]] = {}
  current_names: list[str] = []
  for raw_line in lines:
    line = raw_line.strip()
    if line.startswith("### "):
      header = line[4:].strip()
      names: list[str] = []
      if header.startswith("`") and "`" in header[1:]:
        for part in header.split("/"):
          segment = part.strip()
          if segment.startswith("`") and "`" in segment[1:]:
            names.append(segment.split("`")[1])
      else:
        primary = header.split()[0]
        if primary:
          names.append(primary)
      current_names = names
      for name in current_names:
        sections.setdefault(name, [])
      continue
    if current_names:
      for name in current_names:
        sections[name].append(line)
  return {name: "\n".join(content).strip() for name, content in sections.items()}


def _parse_widget_fields(
  section_text: str, widget_name: str
) -> tuple[list[WidgetFieldInfo], bool, dict[int, str]]:
  """
  Parse field information from a widget section.

  Returns:
      - list of WidgetFieldInfo
      - is_shorthand (True if array-based shorthand)
      - shorthand_positions (position -> field name mapping)
  """
  fields: list[WidgetFieldInfo] = []
  is_shorthand = False
  shorthand_positions: dict[int, str] = {}

  # Check if this widget uses array-based shorthand
  # Look for patterns like: { "widget": ["field1", "field2", ...] }
  # or numbered positions like "1. `field` (type):"

  # Look for "Schema (array positions):" pattern
  if "Schema (array positions):" in section_text or "array positions" in section_text.lower():
    is_shorthand = True
    # Extract position-based fields (e.g., "1. `prompt` (string):")
    position_pattern = r"^\s*(\d+)\.\s+`?(\w+)`?\s*(?:\(([^)]+)\))?:?\s*(.*)"
    for line in section_text.splitlines():
      match = re.match(position_pattern, line)
      if match:
        pos_str, field_name, field_type_hint, description = match.groups()
        position = int(pos_str) - 1  # Convert to 0-indexed
        shorthand_positions[position] = field_name

        required = "optional" not in (description or "").lower()
        field_type = "string"  # Default
        if field_type_hint:
          field_type = field_type_hint.strip().split(",")[0].strip().lower()

        fields.append(WidgetFieldInfo(name=field_name, required=required, field_type=field_type))

  if not is_shorthand:
    shorthand_json_match = re.search(
      r"{\s*\"[^\"]+\"\s*:\s*\[[^\]]+]", section_text, re.DOTALL | re.MULTILINE
    )
    if shorthand_json_match:
      is_shorthand = True

  # Also look for "Constraints:" section to find required fields
  constraints_match = re.search(
    r"Constraints?:(.+?)(?=\n\n|\Z)", section_text, re.DOTALL | re.IGNORECASE
  )
  if constraints_match and not is_shorthand:
    constraints_section = constraints_match.group(1)
    # Look for "- `field` must be ..." or "- field (type, required)"
    field_pattern = r"-\s+`?(\w+)`?\s+(?:must|should|is)"
    for match in re.finditer(field_pattern, constraints_section):
      field_name = match.group(1)
      if not any(f.name == field_name for f in fields):
        fields.append(WidgetFieldInfo(name=field_name, required=True))

  return fields, is_shorthand, shorthand_positions


def load_widget_registry(path: Path) -> WidgetRegistry:
  """Load a registry of supported widgets from a markdown file."""
  if not path.is_file():
    raise FileNotFoundError(f"Widget definition file not found: {path}")

  content = path.read_text(encoding="utf-8").splitlines()
  sections = _iter_widget_sections(content)
  definitions = {}

  for name, section_text in sections.items():
    fields, is_shorthand, shorthand_positions = _parse_widget_fields(section_text, name)
    definitions[name] = WidgetDefinition(
      name=name,
      description=section_text or "Undocumented widget.",
      fields=fields,
      is_shorthand=is_shorthand,
      shorthand_positions=shorthand_positions,
    )

  return WidgetRegistry(definitions)
