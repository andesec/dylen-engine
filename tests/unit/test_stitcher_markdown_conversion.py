"""Unit tests for Stitcher legacy text conversion into MarkdownText."""

from __future__ import annotations

from app.ai.agents.stitcher import StitcherAgent
from app.ai.pipeline.contracts import StructuredSection


def test_stitcher_converts_multikey_legacy_text_objects() -> None:
  """Convert multi-key legacy text objects into a single markdown widget."""
  section = StructuredSection(
    section_number=1,
    json={"section": "S", "items": [{"p": "Hello", "meta": {"ignored": True}}, {"warn": "Be careful", "title": "Pitfall", "extra": 1}, {"ul": ["a", "b"], "note": "extra ignored"}, {"paragraph": "Legacy paragraph", "align": "center"}], "subsections": []},
  )
  out = StitcherAgent._output_dle_shorthand([section])
  items = out[0].payload["items"]
  assert items[0] == {"markdown": ["Hello"]}
  assert items[1] == {"markdown": ["**Warning:** Pitfall: Be careful"]}
  assert items[2] == {"markdown": ["- a\n- b"]}
  assert items[3] == {"markdown": ["Legacy paragraph", "center"]}
