"""Markdown length enforcement helpers.

Why:
  - Very large markdown payloads can consume excessive memory/CPU during validation,
    persistence, and rendering, creating DoS risk.
  - The Markdown widget schema intentionally accepts arbitrary text, so size limits
    must be enforced at runtime using operator-configurable limits.

How:
  - Traverse lesson-shaped payloads and emit Pydantic-style error strings with dot
    paths so downstream repair tooling can target the right widgets.
  - Provide section-index buckets (1-based) to support per-section repair flows.
"""

from __future__ import annotations

from typing import Any


def collect_overlong_markdown_errors(payload: Any, *, max_markdown_chars: int) -> list[str]:
  """Return validation-style error strings for markdown widgets that exceed max length.

  How:
    - Emits dot paths aligned with the lesson schema:
      - blocks.<section_index>.items.<item_index>.markdown.0
      - blocks.<section_index>.subsections.<sub_index>.items.<item_index>.markdown.0
    - Uses 0-based indices to match existing Pydantic error paths in this codebase.
  """
  if max_markdown_chars <= 0:
    raise ValueError("max_markdown_chars must be positive.")
  errors: list[str] = []
  if not isinstance(payload, dict):
    return errors
  blocks = payload.get("blocks")
  if not isinstance(blocks, list):
    return errors
  # Walk sections deterministically so repair targeting stays stable.
  for section_index, section in enumerate(blocks):
    if not isinstance(section, dict):
      continue
    _collect_overlong_markdown_errors_for_section(errors, section, max_markdown_chars=max_markdown_chars, section_index=section_index)
  return errors


def collect_overlong_markdown_errors_by_section(payload: Any, *, max_markdown_chars: int) -> dict[int, list[str]]:
  """Bucket overlong markdown errors by 1-based section number.

  Why:
    - Repair is executed per section in the pipeline, so we need a stable mapping
      from overlong content -> section index.
  """
  if max_markdown_chars <= 0:
    raise ValueError("max_markdown_chars must be positive.")
  grouped: dict[int, list[str]] = {}
  if not isinstance(payload, dict):
    return grouped
  blocks = payload.get("blocks")
  if not isinstance(blocks, list):
    return grouped
  # Keep ordering deterministic to reduce repeated repair churn.
  for section_index, section in enumerate(blocks):
    if not isinstance(section, dict):
      continue
    errors: list[str] = []
    _collect_overlong_markdown_errors_for_section(errors, section, max_markdown_chars=max_markdown_chars, section_index=section_index)
    if errors:
      grouped[section_index + 1] = errors
  return grouped


def _collect_overlong_markdown_errors_for_section(errors: list[str], section: dict[str, Any], *, max_markdown_chars: int, section_index: int) -> None:
  """Collect overlong markdown errors for a section payload and append to list."""
  # Validate all top-level section items.
  items = section.get("items")
  if isinstance(items, list):
    for item_index, item in enumerate(items):
      _collect_overlong_markdown_errors_for_item(errors, item, max_markdown_chars=max_markdown_chars, path_prefix=f"blocks.{section_index}.items.{item_index}")
  # Validate subsection items as well because they can carry Markdown widgets.
  subsections = section.get("subsections")
  if isinstance(subsections, list):
    for sub_index, subsection in enumerate(subsections):
      if not isinstance(subsection, dict):
        continue
      sub_items = subsection.get("items")
      if not isinstance(sub_items, list):
        continue
      for item_index, item in enumerate(sub_items):
        _collect_overlong_markdown_errors_for_item(errors, item, max_markdown_chars=max_markdown_chars, path_prefix=f"blocks.{section_index}.subsections.{sub_index}.items.{item_index}")


def _collect_overlong_markdown_errors_for_item(errors: list[str], item: Any, *, max_markdown_chars: int, path_prefix: str) -> None:
  """Collect markdown-length errors for a single widget item."""
  if not isinstance(item, dict):
    return
  markdown = item.get("markdown")
  if not isinstance(markdown, list) or not markdown:
    return
  md = markdown[0]
  if not isinstance(md, str):
    return
  # Emit an actionable message that includes the hard limit for repair prompts.
  if len(md) > max_markdown_chars:
    errors.append(f"{path_prefix}.markdown.0: markdown exceeds max length of {max_markdown_chars} chars.")
