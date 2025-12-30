"""Deterministic repair utilities for common lesson JSON issues."""

from __future__ import annotations

import copy
from typing import Any


def attempt_deterministic_repair(
    lesson_json: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    """
    Attempt to repair common validation errors without AI intervention.

    Based on proven repair patterns from the DLE frontend app.js.
    Returns the repaired JSON (may still have errors if not all fixable).
    """
    repaired = copy.deepcopy(lesson_json)

    # Fix missing version
    if "version" not in repaired:
        repaired["version"] = "1.0"

    # Fix missing or empty title
    if (
        "title" not in repaired
        or not repaired.get("title")
        or not str(repaired.get("title")).strip()
    ):
        repaired["title"] = "Untitled Lesson"

    # Fix missing blocks
    if "blocks" not in repaired:
        repaired["blocks"] = []

    # Fix blocks that are not arrays
    if not isinstance(repaired.get("blocks"), list):
        blocks = repaired.get("blocks")
        if isinstance(blocks, dict):
            # Wrap single block object into array
            repaired["blocks"] = [blocks]
        else:
            repaired["blocks"] = []

    # Normalize blocks
    normalized_blocks = []
    for idx, block in enumerate(repaired.get("blocks", [])):
        normalized_block = _normalize_block(block, idx)
        if normalized_block:
            normalized_blocks.append(normalized_block)

    repaired["blocks"] = normalized_blocks

    return repaired


def _normalize_block(block: Any, idx: int) -> dict[str, Any] | None:
    """
    Normalize a single block, handling common structural issues.

    Based on the frontend normalizeBlocks function.
    """
    # Remove null/None/empty blocks
    if block is None:
        return None

    # Wrap bare strings into a section
    if isinstance(block, str):
        return {"section": "Untitled Section", "items": [{"p": block}]}

    # Must be a dict at this point
    if not isinstance(block, dict):
        return None

    # Handle quiz widgets at block level - wrap into section
    if "quiz" in block and "section" not in block:
        return {"section": "Quiz", "items": [block]}

    # Ensure sections have required fields
    if "section" in block or is_section_like(block):
        section = block.get("section")
        if not section or not str(section).strip():
            block["section"] = f"Section {idx + 1}"

        # Ensure items field exists and is a list
        if "items" not in block or not isinstance(block.get("items"), list):
            block["items"] = []

        # Normalize items within the section
        normalized_items = []
        for item_idx, item in enumerate(block.get("items", [])):
            normalized_item = _normalize_widget(item, item_idx)
            if normalized_item:
                normalized_items.append(normalized_item)

        block["items"] = normalized_items

        # Fix subsections if present
        if "subsections" in block:
            if not isinstance(block["subsections"], list):
                block["subsections"] = []
            else:
                # Recursively normalize subsections
                normalized_subsections = []
                for sub_idx, sub in enumerate(block["subsections"]):
                    normalized_sub = _normalize_block(sub, sub_idx)
                    if normalized_sub:
                        normalized_subsections.append(normalized_sub)
                block["subsections"] = normalized_subsections

        return block

    # For non-section blocks, wrap them into a section
    return {"section": "Untitled Section", "items": [block]}


def is_section_like(block: dict[str, Any]) -> bool:
    """Check if a block looks like it should be a section."""
    return "items" in block or "subsections" in block


def _normalize_widget(widget: Any, idx: int) -> dict[str, Any] | None:
    """
    Normalize a widget, handling common field issues.

    Based on validation patterns from the frontend.
    """
    if widget is None:
        return None

    # Wrap bare strings into paragraph widgets
    if isinstance(widget, str):
        return {"p": widget}

    if not isinstance(widget, dict):
        return None

    # Fix specific widget types based on validation rules

    # Quiz: ensure required fields
    if "quiz" in widget:
        quiz_data = widget.get("quiz", {})
        if isinstance(quiz_data, dict):
            if "questions" not in quiz_data or not isinstance(quiz_data.get("questions"), list):
                quiz_data["questions"] = []
            widget["quiz"] = quiz_data

    # Fill-blank: ensure sentence has ___
    if "fill_blank" in widget or "fillBlank" in widget:
        fb_data = widget.get("fill_blank") or widget.get("fillBlank", {})
        if isinstance(fb_data, dict):
            sentence = fb_data.get("sentence", "")
            if isinstance(sentence, str) and "___" not in sentence:
                # Can't automatically fix this - would need AI
                pass

    # Table: ensure rows is an array
    if "table" in widget:
        table_data = widget.get("table")
        if isinstance(table_data, dict):
            if "rows" not in table_data or not isinstance(table_data.get("rows"), list):
                table_data["rows"] = []
            widget["table"] = table_data
        elif isinstance(table_data, list):
            # Shorthand: array of rows
            widget["table"] = {"rows": table_data}

    # Comparison/compare: ensure items/rows is an array
    if "comparison" in widget or "compare" in widget:
        comp_data = widget.get("comparison") or widget.get("compare")
        if isinstance(comp_data, dict):
            if "items" not in comp_data or not isinstance(comp_data.get("items"), list):
                comp_data["items"] = []

    # List: ensure items is an array
    if "list" in widget or "ul" in widget or "ol" in widget:
        list_key = "list" if "list" in widget else ("ul" if "ul" in widget else "ol")
        list_data = widget.get(list_key)
        if isinstance(list_data, dict):
            if "items" not in list_data or not isinstance(list_data.get("items"), list):
                list_data["items"] = []
            widget[list_key] = list_data
        elif not isinstance(list_data, list):
            # Shorthand expects an array
            widget[list_key] = []

    # Collapsible: ensure title and content
    if "collapsible" in widget:
        coll_data = widget.get("collapsible", {})
        if isinstance(coll_data, dict):
            if "title" not in coll_data or not coll_data.get("title"):
                coll_data["title"] = "Collapsible Section"
            if "content" not in coll_data or not coll_data.get("content"):
                coll_data["content"] = ""
            widget["collapsible"] = coll_data

    return widget


def is_worth_ai_repair(errors: list[str]) -> bool:
    """
    Determine if errors are complex enough to warrant AI repair.

    Returns False if errors are only simple/structural issues that
    deterministic repair should have fixed.
    """
    # If no errors remain, no need for AI repair
    if not errors:
        return False

    # Patterns for simple structural errors that deterministic repair handles
    simple_patterns = [
        "version",
        "title",
        "blocks",
        "section",
        "items",
        "missing",
        # "must be",  # Too broad, can prevent AI repair of complex value errors
        "required",
        "empty",
    ]

    # Check if ANY error is complex (not just structural)
    complex_error_found = False
    for error in errors:
        error_lower = error.lower()
        # If error doesn't match any simple pattern, it's complex
        is_simple = any(pattern in error_lower for pattern in simple_patterns)
        if not is_simple:
            complex_error_found = True
            break

    # Only use AI repair if there are complex errors
    return complex_error_found
