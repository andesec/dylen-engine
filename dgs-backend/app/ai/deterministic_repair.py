"""Deterministic repair utilities for common lesson JSON issues."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

MAX_TEXT_LENGTH = 800
MAX_LIST_ITEMS = 40
MAX_TABLE_ROWS = 30
MAX_NESTING_DEPTH = 3
MAX_FLOW_DEPTH = 5
MAX_CHECKLIST_DEPTH = 3


def attempt_deterministic_repair(lesson_json: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    """
    Repair lesson payloads by normalizing structure and shorthand widgets.

    This mirrors frontend editor repair heuristics to reduce avoidable AI calls while
    keeping output aligned with the shorthand widget schema.
    """
    # Preserve the incoming payload to avoid side effects for callers.
    _ = errors
    repaired = copy.deepcopy(lesson_json)
    # Normalize the lesson into the backend schema so validation can re-run.
    normalized = _normalize_lesson(repaired)
    return normalized


def _normalize_lesson(payload: Any) -> dict[str, Any]:
    """Normalize lesson-level structure into a valid dict payload."""
    # Wrap top-level arrays into lesson objects to match backend expectations.
    if isinstance(payload, list):
        payload = {"title": "Untitled Lesson", "blocks": payload}
    # Fall back to a minimal lesson shell when payloads are not dicts.
    if not isinstance(payload, dict):
        return {"title": "Untitled Lesson", "blocks": []}
    # Normalize the lesson title to ensure schema validation succeeds.
    title = _sanitize_text(payload.get("title"))
    if not title:
        title = "Untitled Lesson"
    # Normalize blocks into a list of section objects.
    blocks = payload.get("blocks")
    if isinstance(blocks, dict):
        blocks = [blocks]
    if not isinstance(blocks, list):
        blocks = []
    normalized_blocks: list[dict[str, Any]] = []
    # Normalize each block with section-aware repair logic.
    for idx, block in enumerate(blocks):
        normalized = _normalize_block(block, idx, 0)
        if normalized is not None:
            normalized_blocks.append(normalized)
    cleaned = dict(payload)
    cleaned["title"] = title
    cleaned["blocks"] = normalized_blocks
    return cleaned


def _normalize_block(block: Any, idx: int, depth: int) -> dict[str, Any] | None:
    """Normalize a block into a section payload."""
    # Skip empty blocks entirely to avoid creating empty sections.
    if block is None:
        return None
    # Wrap raw strings into sections with a paragraph widget.
    if isinstance(block, str):
        text = _sanitize_text(block)
        if not text:
            return None
        return {"section": "Untitled Section", "items": [{"p": text}]}
    # Drop unsupported block shapes that cannot be normalized safely.
    if not isinstance(block, dict):
        return None
    # Promote top-level quiz blocks into section-wrapped mcqs widgets.
    if "quiz" in block or "mcqs" in block:
        mcqs_source = block.get("mcqs") or block.get("quiz") or block
        mcqs = _normalize_mcqs_widget(mcqs_source)
        if mcqs is None:
            return None
        return {"section": "Quiz", "items": [{"mcqs": mcqs}]}
    # Normalize section-like blocks with items/subsections.
    if "section" in block or _is_section_like(block):
        return _normalize_section_block(block, idx, depth)
    # Wrap standalone widgets into a new section.
    items = _normalize_widget_item(block)
    if not items:
        return None
    return {"section": "Untitled Section", "items": items}


def _is_section_like(block: dict[str, Any]) -> bool:
    """Identify objects that should be treated as sections based on keys."""
    # Treat blocks with items/subsections as sections for normalization.
    return "items" in block or "subsections" in block


def _normalize_section_block(section: dict[str, Any], idx: int, depth: int) -> dict[str, Any] | None:
    """Normalize section fields, items, and nested subsections."""
    # Require a dictionary payload for section normalization.
    if not isinstance(section, dict):
        return None
    # Sanitize the section title and ensure a fallback placeholder.
    title = _sanitize_text(section.get("section") or section.get("title") or "")
    if not title:
        title = f"Section {idx + 1}"
    # Coerce items into a list so widgets can be normalized consistently.
    raw_items = _coerce_items_list(section.get("items"))
    normalized_items: list[dict[str, Any]] = []
    # Normalize each item and flatten multi-key splits.
    for item in raw_items:
        normalized_items.extend(_normalize_widget_item(item))

    # Normalize subsections within depth limits to avoid runaway nesting.
    subsections = section.get("subsections")
    normalized_subs: list[dict[str, Any]] = []
    if isinstance(subsections, list) and depth < MAX_NESTING_DEPTH:
        for sub_idx, sub in enumerate(subsections):
            normalized = _normalize_block(sub, sub_idx, depth + 1)
            if normalized is not None:
                normalized_subs.append(normalized)

    # Return None only if both items and subsections are empty.
    if not normalized_items and not normalized_subs:
        return None

    cleaned: dict[str, Any] = {"section": title, "items": normalized_items}
    if normalized_subs:
        cleaned["subsections"] = normalized_subs
    if "id" in section:
        cleaned["id"] = section["id"]
    return cleaned


def _coerce_items_list(value: Any) -> list[Any]:
    """Coerce section items into a list while preserving raw content."""
    # Preserve existing lists to avoid unnecessary reshaping.
    if isinstance(value, list):
        return value
    # Wrap single widget mappings to keep list semantics.
    if isinstance(value, dict):
        return [value]
    # Parse JSON-like strings into lists when possible.
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        return [stripped]
    # Ignore missing values, but preserve scalar content as text.
    if value is None:
        return []
    return [str(value)]


def _normalize_widget_item(item: Any) -> list[dict[str, Any]]:
    """Normalize a single widget or split multi-key payloads into widgets."""
    # Convert raw strings into paragraph widgets.
    if isinstance(item, str):
        text = _sanitize_text(item)
        if not text:
            return []
        return [{"p": text}]
    # Drop non-dict widgets that cannot be mapped to shorthand.
    if not isinstance(item, dict):
        return []
    # Split multi-key shorthand widgets into separate items.
    shorthand_keys = {
        "p",
        "warn",
        "err",
        "success",
        "flip",
        "tr",
        "ex",
        "fillblank",
        "blank",
        "ul",
        "ol",
        "table",
        "compare",
        "swipecards",
        "swipe",
        "freeText",
        "inputLine",
        "stepFlow",
        "asciiDiagram",
        "checklist",
        "mcqs",
        "quiz",
        "interactiveTerminal",
        "terminalDemo",
        "codeEditor",
        "treeview",
    }
    raw_keys = [key for key in item.keys() if not key.startswith("_")]
    hits = [key for key in raw_keys if key in shorthand_keys]
    if "type" not in item and len(hits) > 1:
        split_items: list[dict[str, Any]] = []
        for key in hits:
            split_items.extend(_normalize_widget_item({key: item[key]}))
        return split_items
    # Normalize paragraph widgets.
    if "p" in item:
        text = _sanitize_text(item.get("p"))
        if not text:
            return []
        return [{"p": text}]
    # Normalize callout widgets.
    if any(key in item for key in ("warn", "err", "success")):
        key = "warn" if "warn" in item else "err" if "err" in item else "success"
        text = _sanitize_text(item.get(key))
        if not text:
            return []
        return [{key: text}]
    # Normalize translation widgets with language prefixes.
    if "tr" in item or "ex" in item:
        pair = item.get("tr") or item.get("ex")
        if not isinstance(pair, list) or len(pair) < 2:
            return []
        primary = _normalize_translation_entry(pair[0])
        secondary = _normalize_translation_entry(pair[1])
        if not primary or not secondary:
            return []
        return [{"tr": [primary, secondary]}]
    # Normalize list widgets.
    if "ul" in item or "ol" in item:
        key = "ul" if "ul" in item else "ol"
        items = _normalize_list_items(item.get(key))
        if not items:
            return []
        return [{key: items}]
    # Normalize flipcards.
    if "flip" in item:
        flip = item.get("flip")
        if not isinstance(flip, list) or len(flip) < 2:
            return []
        front = _sanitize_text(flip[0])
        back = _sanitize_text(flip[1])
        if not front or not back:
            return []
        payload: list[str] = [front, back]
        if len(flip) > 2 and flip[2]:
            payload.append(_sanitize_text(flip[2]))
        if len(flip) > 3 and flip[3]:
            payload.append(_sanitize_text(flip[3]))
        return [{"flip": payload}]
    # Normalize fill-blank widgets.
    if "fillblank" in item or "blank" in item:
        source = item.get("fillblank") if "fillblank" in item else item.get("blank")
        fillblank = _normalize_fillblank_widget(source)
        if fillblank is None:
            return []
        return [{"fillblank": fillblank}]
    # Normalize MCQs widgets.
    if "mcqs" in item or "quiz" in item:
        source = item.get("mcqs") if "mcqs" in item else item.get("quiz")
        mcqs = _normalize_mcqs_widget(source)
        if mcqs is None:
            return []
        return [{"mcqs": mcqs}]
    # Normalize swipecards widgets.
    if "swipecards" in item or "swipe" in item:
        source = item.get("swipecards") if "swipecards" in item else item.get("swipe")
        swipecards = _normalize_swipecards_widget(source)
        if swipecards is None:
            return []
        return [{"swipecards": swipecards}]
    # Normalize tables and comparisons.
    if "table" in item:
        rows = _normalize_table_rows(item.get("table"))
        if rows is None:
            return []
        return [{"table": rows}]
    if "compare" in item:
        rows = _normalize_compare_rows(item.get("compare"))
        if rows is None:
            return []
        return [{"compare": rows}]
    # Normalize free text widgets.
    if "freeText" in item:
        free_text = _normalize_free_text_widget(item.get("freeText"))
        if free_text is None:
            return []
        return [{"freeText": free_text}]
    # Normalize input line widgets.
    if "inputLine" in item:
        input_line = _normalize_input_line_widget(item.get("inputLine"))
        if input_line is None:
            return []
        return [{"inputLine": input_line}]
    # Normalize step flow widgets.
    if "stepFlow" in item:
        step_flow = _normalize_step_flow_widget(item.get("stepFlow"))
        if step_flow is None:
            return []
        return [{"stepFlow": step_flow}]
    # Normalize ascii diagram widgets.
    if "asciiDiagram" in item:
        diagram = _normalize_ascii_diagram_widget(item.get("asciiDiagram"))
        if diagram is None:
            return []
        return [{"asciiDiagram": diagram}]
    # Normalize checklist widgets.
    if "checklist" in item:
        checklist = _normalize_checklist_widget(item.get("checklist"))
        if checklist is None:
            return []
        return [{"checklist": checklist}]
    # Pass through interactive terminal and demo widgets when shaped correctly.
    if "interactiveTerminal" in item and isinstance(item.get("interactiveTerminal"), dict):
        payload = item.get("interactiveTerminal")
        # Repair: migrate 'lead' to 'title'
        if "lead" in payload and "title" not in payload:
            payload["title"] = payload.pop("lead")
        return [{"interactiveTerminal": payload}]
    if "terminalDemo" in item and isinstance(item.get("terminalDemo"), dict):
        payload = item.get("terminalDemo")
        # Repair: migrate 'lead' to 'title'
        if "lead" in payload and "title" not in payload:
            payload["title"] = payload.pop("lead")
        return [{"terminalDemo": payload}]
    # Pass through codeEditor and treeview widgets when they are arrays.
    if "codeEditor" in item and isinstance(item.get("codeEditor"), list):
        return [{"codeEditor": item.get("codeEditor")}]
    if "treeview" in item and isinstance(item.get("treeview"), list):
        return [{"treeview": item.get("treeview")}]
    return []


def _sanitize_text(value: Any, limit: int = MAX_TEXT_LENGTH) -> str:
    """Trim, coerce, and truncate text fields without adding new content."""
    # Normalize scalars into trimmed strings.
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    # Truncate overly long strings to match frontend repair behavior.
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _normalize_translation_entry(value: Any) -> str:
    """Normalize translation entries into `CODE: text` format."""
    # Preserve existing language prefixes when present.
    raw = _sanitize_text(value)
    if not raw:
        return ""
    match = re.match(r"^\s*([A-Za-z]{2,3})\s*[:\-]\s*(.*)$", raw)
    if not match:
        return raw
    code = match.group(1).upper()
    text = _sanitize_text(match.group(2))
    return f"{code}: {text}" if text else ""


def _normalize_list_items(items: Any) -> list[str]:
    """Normalize list items into a clean list of strings."""
    # Coerce list-like inputs into a normalized list.
    raw_list = items if isinstance(items, list) else [items]
    cleaned = [_sanitize_text(entry) for entry in raw_list]
    cleaned = [entry for entry in cleaned if entry]
    if len(cleaned) > MAX_LIST_ITEMS:
        cleaned = cleaned[:MAX_LIST_ITEMS]
    return cleaned


def _normalize_table_rows(rows: Any) -> list[list[str]] | None:
    """Normalize table rows into a list of string rows."""
    # Require row lists to avoid fabricating tabular structure.
    if not isinstance(rows, list):
        return None
    cleaned_rows: list[list[str]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        cleaned_row = [_sanitize_text(cell) for cell in row]
        cleaned_row = [cell for cell in cleaned_row if cell]
        if cleaned_row:
            cleaned_rows.append(cleaned_row)
    if len(cleaned_rows) > MAX_TABLE_ROWS:
        cleaned_rows = cleaned_rows[:MAX_TABLE_ROWS]
    if len(cleaned_rows) < 2:
        return None
    return cleaned_rows


def _normalize_compare_rows(rows: Any) -> list[list[str]] | None:
    """Normalize comparison rows into at least two columns."""
    # Normalize via table rules, then enforce two-column rows.
    cleaned = _normalize_table_rows(rows)
    if cleaned is None:
        return None
    normalized: list[list[str]] = []
    for row in cleaned:
        if len(row) < 2:
            return None
        normalized.append(row)
    return normalized


def _normalize_fillblank_widget(fillblank: Any) -> list[str] | None:
    """Normalize fillblank widgets into the required 4-element array."""
    # Accept list or dict-based fillblank payloads.
    if isinstance(fillblank, dict):
        fillblank = [fillblank.get("sentence"), fillblank.get("answer"), fillblank.get("hint"), fillblank.get("explanation")]
    if not isinstance(fillblank, list) or len(fillblank) < 4:
        return None
    cleaned = [_sanitize_text(entry) for entry in fillblank[:4]]
    if not cleaned[0] or "___" not in cleaned[0]:
        return None
    if not all(cleaned):
        return None
    return cleaned


def _normalize_mcqs_widget(mcqs: Any) -> dict[str, Any] | None:
    """Normalize mcqs payloads into the required title/questions structure."""
    # Require dict payloads to avoid fabricating question structure.
    if not isinstance(mcqs, dict):
        return None
    title = _sanitize_text(mcqs.get("title") or "MCQs")
    questions = mcqs.get("questions")
    if not isinstance(questions, list):
        q = mcqs.get("q") or mcqs.get("question") or mcqs.get("prompt") or mcqs.get("text")
        c = mcqs.get("c") or mcqs.get("choices") or mcqs.get("options") or mcqs.get("answers")
        a = mcqs.get("a") or mcqs.get("answer") or mcqs.get("correct") or mcqs.get("correctIndex")
        e = mcqs.get("e") or mcqs.get("explanation") or mcqs.get("why") or mcqs.get("reason")
        if q or c or a or e:
            questions = [{"q": q, "c": c, "a": a, "e": e}]
    if not isinstance(questions, list) or not questions:
        return None
    cleaned_questions: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        q_text = _sanitize_text(question.get("q") or question.get("question") or question.get("prompt") or question.get("text"))
        choices = _normalize_list_items(question.get("c") or question.get("choices") or question.get("options") or question.get("answers"))
        explanation = _sanitize_text(question.get("e") or question.get("explanation") or question.get("why") or question.get("reason"))
        if not q_text or len(choices) < 2 or not explanation:
            return None
        answer = question.get("a") or question.get("answer") or question.get("correct") or question.get("correctIndex")
        answer_index = _coerce_mcqs_answer_index(answer, choices)
        if answer_index is None:
            return None
        cleaned_questions.append({"q": q_text, "c": choices, "a": answer_index, "e": explanation})
    if not cleaned_questions:
        return None
    return {"title": title or "MCQs", "questions": cleaned_questions}


def _coerce_mcqs_answer_index(answer: Any, choices: list[str]) -> int | None:
    """Coerce mcqs answers into a valid choice index."""
    # Accept explicit integer indices when in range.
    if isinstance(answer, int):
        return answer if 0 <= answer < len(choices) else None
    # Match string answers to choice text when possible.
    if isinstance(answer, str):
        lowered = answer.strip().lower()
        for idx, choice in enumerate(choices):
            if choice.strip().lower() == lowered:
                return idx
    return None


def _normalize_swipecards_widget(swipecards: Any) -> list[Any] | None:
    """Normalize swipecards widgets into [title, buckets, cards]."""
    # Accept list and dict payloads to mirror frontend repair behavior.
    title = ""
    labels = None
    cards = None
    if isinstance(swipecards, list):
        if len(swipecards) >= 1:
            title = swipecards[0]
        if len(swipecards) >= 2:
            labels = swipecards[1]
        if len(swipecards) >= 3:
            cards = swipecards[2]
    elif isinstance(swipecards, dict):
        title = swipecards.get("title") or swipecards.get("instructions") or swipecards.get("prompt") or ""
        labels = swipecards.get("labels") or swipecards.get("buckets") or swipecards.get("bucketLabels")
        cards = swipecards.get("cards")
    title = _sanitize_text(title) or "Swipe Drill"
    labels_list = _normalize_list_items(labels)
    if len(labels_list) < 2:
        labels_list = ["Left", "Right"]
    if not isinstance(cards, list):
        return None
    cleaned_cards: list[list[Any]] = []
    for card in cards:
        if isinstance(card, list) and len(card) >= 3:
            text, idx, feedback = card[0], card[1], card[2]
        elif isinstance(card, dict):
            text = card.get("text") or card.get("front") or card.get("prompt") or card.get("card")
            idx = card.get("correct") or card.get("answer") or card.get("bucket") or card.get("correctIndex")
            feedback = card.get("feedback") or card.get("explanation") or card.get("reason")
        else:
            text, idx, feedback = card, 0, ""
        text = _sanitize_text(text)
        feedback = _sanitize_text(feedback)
        if not text or not feedback:
            return None
        if not isinstance(idx, int) or idx not in (0, 1):
            idx = 0
        cleaned_cards.append([text, idx, feedback])
    if not cleaned_cards:
        return None
    if len(cleaned_cards) > MAX_LIST_ITEMS:
        cleaned_cards = cleaned_cards[:MAX_LIST_ITEMS]
    return [title, labels_list[:2], cleaned_cards]


def _normalize_free_text_widget(free_text: Any) -> list[Any] | None:
    """Normalize freeText widgets into the expected array shape."""
    # Accept list payloads and coerce scalars into a prompt.
    if isinstance(free_text, list):
        items = free_text
    else:
        items = [free_text]
    prompt = _sanitize_text(items[0] if items else "")
    if not prompt:
        return None
    seed_locked = _sanitize_text(items[1]) if len(items) > 1 and items[1] is not None else None
    lang = _sanitize_text(items[2]) if len(items) > 2 and items[2] is not None else None
    wordlist = _sanitize_text(items[3]) if len(items) > 3 and items[3] is not None else None
    payload: list[Any] = [prompt]
    if seed_locked is not None:
        payload.append(seed_locked)
    if lang is not None:
        payload.append(lang)
    if wordlist is not None:
        payload.append(wordlist)
    return payload


def _normalize_input_line_widget(input_line: Any) -> list[Any] | None:
    """Normalize inputLine widgets into the expected array shape."""
    # Accept list payloads and coerce scalars into a prompt.
    if isinstance(input_line, list):
        items = input_line
    else:
        items = [input_line]
    prompt = _sanitize_text(items[0] if items else "")
    if not prompt:
        return None
    lang = _sanitize_text(items[1]) if len(items) > 1 and items[1] is not None else None
    wordlist = _sanitize_text(items[2]) if len(items) > 2 and items[2] is not None else None
    payload: list[Any] = [prompt]
    if lang is not None:
        payload.append(lang)
    if wordlist is not None:
        payload.append(wordlist)
    return payload


def _normalize_step_flow_widget(step_flow: Any) -> list[Any] | None:
    """Normalize stepFlow widgets into [title, flow]."""
    # Accept list payloads with title and flow data.
    if not isinstance(step_flow, list) or len(step_flow) < 2:
        return None
    title = _sanitize_text(step_flow[0])
    flow = step_flow[1]
    if not title or not isinstance(flow, list) or not flow:
        return None
    normalized_flow = _normalize_flow_nodes(flow, 0)
    if not normalized_flow:
        return None
    return [title, normalized_flow]


def _normalize_flow_nodes(nodes: list[Any], depth: int) -> list[Any] | None:
    """Normalize step flow nodes without exceeding nesting limits."""
    # Abort if nesting exceeds schema constraints.
    if depth > MAX_FLOW_DEPTH:
        return None
    normalized: list[Any] = []
    for node in nodes:
        if isinstance(node, str):
            text = _sanitize_text(node)
            if text:
                normalized.append(text)
            continue
        if isinstance(node, list):
            if not node:
                continue
            branch: list[Any] = []
            for option in node:
                if not isinstance(option, list) or len(option) != 2:
                    return None
                label = _sanitize_text(option[0])
                steps = option[1]
                if not label or not isinstance(steps, list):
                    return None
                normalized_steps = _normalize_flow_nodes(steps, depth + 1)
                if normalized_steps is None:
                    return None
                branch.append([label, normalized_steps])
            if branch:
                normalized.append(branch)
            continue
        return None
    return normalized


def _normalize_ascii_diagram_widget(ascii_diagram: Any) -> list[str] | None:
    """Normalize asciiDiagram widgets into [title, diagram]."""
    # Require at least one element (if it's a headless diagram) or two (title + diagram).
    if not isinstance(ascii_diagram, list) or not ascii_diagram:
        return None

    # Heuristic: Check if the first element looks like a diagram line rather than a title.
    # If the first element starts with box-drawing characters or has a high symbol density,
    # we assume the LLM omitted the title and started straight with the diagram.
    first_elem = str(ascii_diagram[0])
    is_headless = False
    
    # Common box drawing characters and non-alphanumeric symbols often found in diagrams
    diagram_start_chars = {'+', '|', '┌', '└', '─', '│', '├', '┤', '┬', '┴', '┼', '*', '#', '<', '>', '/'}
    
    if first_elem:
        stripped_start = first_elem.strip()
        if stripped_start and (stripped_start[0] in diagram_start_chars):
            is_headless = True
        
        # Fallback: formatting characters vs text ratio? 
        # For now, the start char check is usually sufficient for "┌" or "+" style boxes.

    if is_headless:
        title = "Diagram"
        # Join ALL elements as lines
        diagram_lines = [str(item) for item in ascii_diagram]
        diagram = "\n".join(diagram_lines)
    elif len(ascii_diagram) < 2:
        # Not headless, but only 1 element? If it's just a title, we have no diagram.
        return None
    else:
        # Standard case: [title, (diagram...)]
        title = _sanitize_text(ascii_diagram[0])
        
        # Handle nested list (Repairer output: [title, [lines...]])
        if isinstance(ascii_diagram[1], list):
            diagram_lines = [str(line) for line in ascii_diagram[1]]
            diagram = "\n".join(diagram_lines)
        
        # Handle flat list (Gatherer output: [title, line1, line2, ...])
        else:
            # Join all subsequent elements as lines
            diagram_lines = [str(item) for item in ascii_diagram[1:]]
            diagram = "\n".join(diagram_lines)

    if not title:
        title = "Diagram"
    if not diagram:
        return None
        
    return [title, diagram]


def _normalize_checklist_widget(checklist: Any) -> list[Any] | None:
    """Normalize checklist widgets into [title, tree]."""
    # Require checklist arrays with a title and tree list.
    if not isinstance(checklist, list) or len(checklist) < 2:
        return None
    title = _sanitize_text(checklist[0])
    tree = checklist[1]
    if not title or not isinstance(tree, list) or not tree:
        return None
    normalized_tree = _normalize_checklist_tree(tree, 1)
    if normalized_tree is None:
        return None
    return [title, normalized_tree]


def _normalize_checklist_tree(nodes: list[Any], depth: int) -> list[Any] | None:
    """Normalize checklist trees within depth limits."""
    # Stop recursion when nesting exceeds schema constraints.
    if depth > MAX_CHECKLIST_DEPTH:
        return None
    normalized: list[Any] = []
    for node in nodes:
        if isinstance(node, str):
            text = _sanitize_text(node)
            if text:
                normalized.append(text)
            continue
        if isinstance(node, list) and len(node) == 2:
            title = _sanitize_text(node[0])
            children = node[1]
            if not title or not isinstance(children, list):
                return None
            normalized_children = _normalize_checklist_tree(children, depth + 1)
            if normalized_children is None:
                return None
            normalized.append([title, normalized_children])
            continue
        return None
    return normalized


def is_worth_ai_repair(errors: list[str]) -> bool:
    """
    Determine if errors are complex enough to warrant AI repair.

    Returns False if errors are only simple/structural issues that
    deterministic repair should have fixed.
    """
    # Skip AI repair when errors are already resolved.
    if not errors:
        return False
    simple_patterns = [
        "version",
        "title",
        "blocks",
        "section",
        "items",
        "missing",
        "required",
        "empty",
    ]
    # Flag any error that doesn't match a simple structural pattern.
    for error in errors:
        error_lower = error.lower()
        is_simple = any(pattern in error_lower for pattern in simple_patterns)
        if not is_simple:
            return True
    return False
