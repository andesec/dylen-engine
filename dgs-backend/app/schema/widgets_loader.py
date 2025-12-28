"""Utilities for parsing vendored widget documentation into a registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class WidgetDefinition:
    """Record describing a supported widget."""

    name: str
    description: str


class WidgetRegistry:
    """Registry of widget definitions parsed from documentation."""

    def __init__(self, definitions: Dict[str, WidgetDefinition]) -> None:
        self._definitions = definitions

    def is_known(self, widget_type: str) -> bool:
        """Return True if the widget type is defined."""

        return widget_type in self._definitions

    def describe(self, widget_type: str) -> str:
        """Return the description for a widget type."""

        return self._definitions[widget_type].description

    def available_types(self) -> List[str]:
        """List all available widget identifiers."""

        return sorted(self._definitions)


def _iter_widget_sections(lines: Iterable[str]) -> Dict[str, str]:
    sections: Dict[str, List[str]] = {}
    current_names: List[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("### "):
            header = line[4:].strip()
            names: List[str] = []
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


def load_widget_registry(path: Path) -> WidgetRegistry:
    """Load a registry of supported widgets from a markdown file."""

    if not path.is_file():
        raise FileNotFoundError(f"Widget definition file not found: {path}")

    content = path.read_text(encoding="utf-8").splitlines()
    sections = _iter_widget_sections(content)
    definitions = {
        name: WidgetDefinition(name=name, description=description or "Undocumented widget.")
        for name, description in sections.items()
    }
    return WidgetRegistry(definitions)
