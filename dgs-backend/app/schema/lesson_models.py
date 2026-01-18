"""Typed lesson schema models using positional array shorthands."""

from __future__ import annotations

import re
from typing import Any, Union, cast

from pydantic import (
    BaseModel,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

# --- Reusable Validators ---


def coerce_to_str(v: Any) -> str:
    """Coerce value to string, joining lists if necessary."""
    if isinstance(v, list):
        return "\n".join(str(i) for i in v)
    return str(v)


def coerce_to_list_str(v: Any) -> list[str]:
    """Coerce value to list of strings, wrapping single items."""
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(i) for i in v]
    return [str(v)]


# --- Primitive Widgets ---


class ParagraphWidget(BaseModel):
    """Paragraph content widget."""

    p: str

    @field_validator("p", mode="before")
    @classmethod
    def validate_p(cls, v: Any) -> str:
        return coerce_to_str(v)


class WarnWidget(BaseModel):
    """Warning callout."""

    warn: str

    @field_validator("warn", mode="before")
    @classmethod
    def validate_warn(cls, v: Any) -> str:
        return coerce_to_str(v)


class ErrorWidget(BaseModel):
    """Error callout."""

    err: str

    @field_validator("err", mode="before")
    @classmethod
    def validate_err(cls, v: Any) -> str:
        return coerce_to_str(v)


class SuccessWidget(BaseModel):
    """Success callout."""

    success: str

    @field_validator("success", mode="before")
    @classmethod
    def validate_success(cls, v: Any) -> str:
        return coerce_to_str(v)


class FlipWidget(BaseModel):
    """Flipcard widget: [front, back, front_hint?, back_hint?]"""

    flip: list[StrictStr]

    @field_validator("flip", mode="before")
    @classmethod
    def validate_flip_pre(cls, v: Any) -> list[str]:
        # Handle simple [front, back] string input ? No, flip is a list.
        # But if user provides a dict or something?
        if not isinstance(v, list):
            raise ValueError("flip widget must be a list")
        return [str(i) for i in v]

    @field_validator("flip")
    @classmethod
    def validate_flip(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("flip widget must have at least 2 elements: [front, back]")
        if len(v) > 4:
            raise ValueError("flip widget must have at most 4 elements")
        if len(v[0]) > 120:
            raise ValueError("flip front text must be 120 characters or fewer")
        if len(v[1]) > 160:
            raise ValueError("flip back text must be 160 characters or fewer")
        return v


class TranslationWidget(BaseModel):
    """Translation pair widget: [source, target]"""

    tr: list[StrictStr]

    @field_validator("tr", mode="before")
    @classmethod
    def validate_tr_pre(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("tr widget must be a list")
        return [str(i) for i in v]

    @field_validator("tr")
    @classmethod
    def validate_tr(cls, v: list[str]) -> list[str]:
        if len(v) != 2:
            raise ValueError("tr widget must have exactly 2 elements: [source, target]")
        for item in v:
            if not re.match(r"^[A-Za-z]{2,3}[:-]", item):
                raise ValueError("translation entries must start with a language code (e.g. EN:)")
        return v


class FillBlankWidget(BaseModel):
    """Fill-in-the-blank widget: [prompt, answer, hint, explanation]"""

    fillblank: list[StrictStr]

    @field_validator("fillblank", mode="before")
    @classmethod
    def validate_blank_pre(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("fillblank widget must be a list")
        return [str(i) for i in v]

    @field_validator("fillblank")
    @classmethod
    def validate_blank(cls, v: list[str]) -> list[str]:
        if len(v) != 4:
            raise ValueError(
                "fillblank widget must have exactly 4 elements: [prompt, answer, hint, explanation]"
            )
        if "___" not in v[0]:
            raise ValueError("fillblank prompt must include ___ placeholder")
        return v


class UnorderedListWidget(BaseModel):
    """Unordered list widget."""

    ul: list[str]

    @field_validator("ul", mode="before")
    @classmethod
    def validate_ul(cls, v: Any) -> list[str]:
        return coerce_to_list_str(v)


class OrderedListWidget(BaseModel):
    """Ordered list widget."""

    ol: list[str]

    @field_validator("ol", mode="before")
    @classmethod
    def validate_ol(cls, v: Any) -> list[str]:
        return coerce_to_list_str(v)


class TableWidget(BaseModel):
    """Tabular data widget."""

    table: list[list[Any]]  # Relaxed inner type

    @field_validator("table", mode="before")
    @classmethod
    def validate_table_pre(cls, v: Any) -> list[list[Any]]:
        # If user provides list[list[str]], great.
        # If user provides list[str], wrap strings in single-cell rows?
        # Or if user provides dict?
        if not isinstance(v, list):
            raise ValueError("table must be a list of rows")

        # Ensure rows are lists
        normalized = []
        for row in v:
            if isinstance(row, list):
                normalized.append([str(c) for c in row])
            elif isinstance(row, dict):
                # Maybe values?
                normalized.append([str(c) for c in row.values()])
            else:
                # content
                normalized.append([str(row)])
        return normalized

    @field_validator("table")
    @classmethod
    def validate_rows(cls, v: list[list[Any]]) -> list[list[str]]:
        if not v:
            raise ValueError("table requires at least one row")
        for row in v:
            if not row:
                raise ValueError("table rows must not be empty")
        # cast back to list[list[str]] for safety
        return [[str(c) for c in row] for row in v]


class CompareWidget(BaseModel):
    """Two-column comparison widget."""

    compare: list[list[Any]]  # Relaxed

    @field_validator("compare", mode="before")
    @classmethod
    def validate_compare_pre(cls, v: Any) -> list[list[Any]]:
        if not isinstance(v, list):
            raise ValueError("compare must be a list of rows")

        normalized = []
        for row in v:
            if isinstance(row, list):
                normalized.append([str(c) for c in row])
            else:
                normalized.append([str(row)])
        return normalized

    @field_validator("compare")
    @classmethod
    def validate_rows(cls, v: list[list[Any]]) -> list[list[str]]:
        if not v:
            raise ValueError("compare requires at least one row")
        for row in v:
            if len(row) < 2:
                # Pad with empty string if strict 2 cols required, or raise?
                # Schema says "at least two columns".
                # Let's try to be helpful: if 1 col, dup it? Or empty 2nd?
                if len(row) == 1:
                    row.append("")  # Auto-fix single col
                elif len(row) == 0:
                    raise ValueError("compare rows must include at least two columns")
        return [[str(c) for c in row] for row in v]


class SwipeCardsWidget(BaseModel):
    """
    Swipe cards drill widget.
    Format: [title, [bucket1, bucket2], [[text, bucket_idx, feedback], ...]]
    """

    swipecards: list[Any]

    @field_validator("swipecards")
    @classmethod
    def validate_swipecards(cls, v: list[Any]) -> list[Any]:
        if len(v) != 3:
            # Try to salvage if possible?
            # e.g. if len=2 and v[1] is cards but buckets missing? Hard to guess.
            raise ValueError(
                "swipecards widget must have exactly 3 elements: [title, buckets, cards]"
            )

        title, buckets, cards = v[0], v[1], v[2]

        if not isinstance(title, str) or not title:
            raise ValueError("swipecards title must be a non-empty string")

        if not isinstance(buckets, list) or len(buckets) != 2:
            # Heuristic: if buckets is a string "True/False", make it list?
            if isinstance(buckets, str) and "/" in buckets:
                buckets = buckets.split("/")[:2]
            else:
                raise ValueError("swipecards buckets must be a list of two non-empty strings")

        # Ensure strings
        buckets = [str(b) for b in buckets]
        v[1] = buckets

        if not isinstance(cards, list) or not cards:
            raise ValueError("swipecards cards must be a non-empty list")

        for i, card in enumerate(cards):
            if not isinstance(card, list) or len(card) != 3:
                # Heuristic: [text, idx] -> add default feedback?
                if isinstance(card, list) and len(card) == 2:
                    card.append("Correct!" if card[1] == 1 else "Incorrect.")  # default feedback
                else:
                    raise ValueError(
                        f"swipecards card at index {i} must be [text, correct_bucket_idx, feedback]"
                    )

            text, idx, feedback = card[0], card[1], card[2]

            # Coerce index
            if isinstance(idx, str) and idx.isdigit():
                idx = int(idx)

            if not isinstance(idx, int) or idx not in (0, 1):
                # Maybe textual buckets? If so, match? Too complex.
                raise ValueError(f"swipecards card {i} correct_bucket_idx must be 0 or 1")

            cards[i] = [str(text), idx, str(feedback)]

        return v


class FreeTextWidget(BaseModel):
    """
    Free text editor widget (Multi-line only).
    Format: [prompt, seed_locked?, lang?, wordlist_csv?]
    """

    freeText: list[Any]

    @field_validator("freeText", mode="before")
    @classmethod
    def validate_pre(cls, v: Any) -> list[Any]:
        if isinstance(v, str):
            return [v]  # Wrap usage: {"freeText": "Prompt"}
        if not isinstance(v, list):
            raise ValueError("freeText must be [prompt, ...]")
        return v

    @field_validator("freeText")
    @classmethod
    def validate_free_text(cls, v: list[Any]) -> list[Any]:
        if len(v) < 1:
            raise ValueError("freeText widget must have at least a prompt")

        # 0: prompt
        v[0] = str(v[0])

        return v


class InputLineWidget(BaseModel):
    """
    Single line input widget.
    Format: [prompt, lang?, wordlist_csv?]
    """

    inputLine: list[Any]

    @field_validator("inputLine", mode="before")
    @classmethod
    def validate_pre(cls, v: Any) -> list[Any]:
        if isinstance(v, str):
            return [v]
        if not isinstance(v, list):
            raise ValueError("inputLine must be [prompt, ...]")
        return v

    @field_validator("inputLine")
    @classmethod
    def validate_input_line(cls, v: list[Any]) -> list[Any]:
        if len(v) < 1:
            raise ValueError("inputLine widget must have at least a prompt")
        v[0] = str(v[0])
        return v


class StepFlowWidget(BaseModel):
    """
    Step-by-step flow.
    Format: [title, flow]
    flow is a list where items are strings or branch nodes: [[label, steps], ...]
    """

    stepFlow: list[Any]

    @field_validator("stepFlow", mode="before")
    @classmethod
    def validate_pre(cls, v: Any) -> list[Any]:
        # Sometimes AI generates {"stepFlow": [flow]} without title.
        # Or {"stepFlow": flow_list} (missing title) which looks like list[dict] or list[list].
        if isinstance(v, list):
            if len(v) == 1 and isinstance(v[0], list):
                # Assume missing title, insert default
                return ["Steps:", v[0]]
            # If v is a list of steps (lists or strings), wrap it?
            if len(v) > 2 and all(isinstance(x, (str, list)) for x in v):
                # Assume whole list is the flow
                return ["Steps:", v]
        return v

    @field_validator("stepFlow")
    @classmethod
    def validate_step_flow(cls, v: list[Any]) -> list[Any]:
        if len(v) != 2:
            raise ValueError("stepFlow must have exactly 2 elements: [title, flow]")

        title, flow = str(v[0]), v[1]
        if not isinstance(flow, list) or not flow:
            raise ValueError("stepFlow flow must be a non-empty list")

        cls._validate_flow_nodes(flow, depth=0)
        return [title, flow]

    @classmethod
    def _validate_flow_nodes(cls, nodes: list[Any], depth: int):
        if depth > 5:
            raise ValueError("stepFlow nesting depth exceeded (max 5)")

        for i, node in enumerate(nodes):
            if isinstance(node, str):
                continue
            elif isinstance(node, list):
                # Branch node: list of options. Each option is [label, steps]
                if not node:
                    # Empty branch? ignore
                    continue

                # Check if it's a [label, steps] list itself (Single option branch?)
                # Schema says node is list of options. Option is [str, list].
                # If node is [str, list], maybe it's a single option not wrapped in list of options?
                if len(node) == 2 and isinstance(node[0], str) and isinstance(node[1], list):
                    # Wrap it: [[label, steps]]
                    nodes[i] = [node]
                    # re-validate as list of options

                for option in nodes[i]:
                    if not isinstance(option, list) or len(option) != 2:
                        pass  # Warning?
                    else:
                        label, steps = str(option[0]), option[1]
                        if not isinstance(steps, list):
                            pass
                        else:
                            cls._validate_flow_nodes(steps, depth + 1)


class AsciiDiagramWidget(BaseModel):
    """Ascii Diagram: [title, diagram]"""

    asciiDiagram: list[str]

    @field_validator("asciiDiagram", mode="before")
    @classmethod
    def validate_pre(cls, v: Any) -> list[str]:
        # Heuristic: [title, "line1\nline2"] -> [title, ["line1", "line2"]]?
        # Or if v is list[str] len > 2?
        if isinstance(v, list):
            if len(v) > 2:
                # Assume ["Title", "line 1", "line 2", ...]
                # Combine [1:] into diagram string
                return [str(v[0]), "\n".join(str(s) for s in v[1:])]
        return coerce_to_list_str(v)

    @field_validator("asciiDiagram")
    @classmethod
    def validate_diagram(cls, v: list[str]) -> list[str]:
        # Based on typical usage: ["Title", "Diagram block"]
        # If user provides ["Title", "Line1", "Line2"], validate failure in old code.
        # Let's support flattening.
        if len(v) > 2:
            # Merge 1: into a single string with newlines?
            # Or is it expected to be unique?
            # Let's assume ["Title", "Rest of body merged"]
            body = "\n".join(v[1:])
            return [v[0], body]

        if len(v) == 1:
            # Missing title? Or missing body?
            return ["Diagram:", v[0]]

        return v


class ChecklistWidget(BaseModel):
    """
    Checklist: [title, tree]
    tree items are strings or groups: [title, children]
    """

    checklist: list[Any]

    @field_validator("checklist", mode="before")
    @classmethod
    def validate_pre(cls, v: Any) -> list[Any]:
        if isinstance(v, list) and len(v) == 1 and isinstance(v[0], list):
            return ["Checklist:", v[0]]
        return v

    @field_validator("checklist")
    @classmethod
    def validate_checklist(cls, v: list[Any]) -> list[Any]:
        if len(v) != 2:
            raise ValueError("checklist must have exactly 2 elements: [title, tree]")

        title, tree = str(v[0]), v[1]
        if not isinstance(tree, list):
            raise ValueError("checklist tree must be a non-empty list")

        cls._validate_tree(tree, depth=1)
        return [title, tree]

    @classmethod
    def _validate_tree(cls, nodes: list[Any], depth: int):
        if depth > 3:
            return  # Just truncate or ignore?

        for i, node in enumerate(nodes):
            if isinstance(node, str):
                continue
            elif isinstance(node, list):
                if len(node) != 2:
                    # Maybe [title, child1, child2]?
                    if len(node) > 2 and isinstance(node[0], str):
                        # Normalize to [title, [child1, child2]]
                        nodes[i] = [node[0], node[1:]]
                        cls._validate_tree(nodes[i][1], depth + 1)
                        continue

                title, children = str(node[0]), node[1]
                if not isinstance(children, list):
                    pass
                else:
                    cls._validate_tree(children, depth + 1)


class InteractiveTerminalPayload(BaseModel):
    """Interactive terminal payload."""

    title: str = Field(min_length=1)
    rules: list[list[str]]
    guided: list[list[str]] | None = None

    @field_validator("rules", mode="before")
    @classmethod
    def validate_rules_pre(cls, v: Any) -> list[list[str]]:
        if not isinstance(v, list):
            raise ValueError("rules must be list")
        # Fix rules?
        return v

    @field_validator("rules")
    @classmethod
    def validate_rules(cls, v: list[list[str]]) -> list[list[str]]:
        if not v:
            raise ValueError("interactiveTerminal rules must be a non-empty list")

        for i, entry in enumerate(v):
            if not isinstance(entry, list):
                raise ValueError("rule must be list")

            # Auto-fix missing output? [pattern, level] -> [pattern, level, ""]
            if len(entry) == 2:
                entry.append("")

            # Coerce level
            if len(entry) >= 3:
                if entry[1] not in ("ok", "err"):
                    # Fallback
                    entry[1] = "ok"

            v[i] = [str(x) for x in entry[:3]]

        return v

    @field_validator("guided")
    @classmethod
    def validate_guided(cls, v: list[list[str]] | None) -> list[list[str]] | None:
        if v is None:
            return v
        if not v:
            raise ValueError("interactiveTerminal guided steps must be a non-empty list")

        for i, step in enumerate(v):
            if not isinstance(step, list) or len(step) != 2:
                # Auto fix?
                pass
            else:
                v[i] = [str(x) for x in step]
        return v


class InteractiveTerminalWidget(BaseModel):
    """Interactive terminal widget."""

    interactiveTerminal: InteractiveTerminalPayload


class CalendarPayload(BaseModel):  # Does not exist in original but good to verify
    pass  # Placeholder


class TerminalDemoPayload(BaseModel):
    """Terminal demo payload."""

    title: str = Field(min_length=1)
    rules: list[list[Any]] = Field(default_factory=list)  # Relaxed

    @field_validator("rules", mode="before")
    @classmethod
    def validate_rules_pre(cls, v: Any) -> list[list[Any]]:
        if not isinstance(v, list):
            return []
        return v

    @field_validator("rules")
    @classmethod
    def validate_rules(cls, v: list[list[Any]]) -> list[list[Any]]:
        if not v:
            return v  # Allow empty?

        for i, entry in enumerate(v):
            if not isinstance(entry, list):
                continue

            # [command, delay, output]
            if len(entry) == 2:
                # Assume [command, output], default delay?
                # Or [command, delay], default output?
                # Heuristic: if entry[1] is int -> delay
                if isinstance(entry[1], int):
                    entry.append("")
                else:
                    # insert delay 0
                    entry.insert(1, 100)  # 100ms default

            # Ensure types
            if len(entry) >= 3:
                cmd = str(entry[0])
                delay = (
                    int(entry[1])
                    if isinstance(entry[1], (int, str)) and str(entry[1]).isdigit()
                    else 100
                )
                out = str(entry[2])
                v[i] = [cmd, delay, out]

        return v


class TerminalDemoWidget(BaseModel):
    """Terminal demo widget."""

    terminalDemo: TerminalDemoPayload


class CodeEditorWidget(BaseModel):
    """Code Editor: [code, language, readOnly?, highlightedLines?]"""

    codeEditor: list[Any]

    @field_validator("codeEditor")
    @classmethod
    def validate_cv(cls, v: list[Any]) -> list[Any]:
        # Validate positional schema to keep editor rendering deterministic.
        if len(v) < 2:
            raise ValueError("codeEditor must have at least 2 elements: [code, language]")

        code, lang = v[0], v[1]
        if not isinstance(code, (str, dict, list)):  # code can be object if json
            pass

        if not isinstance(lang, str):
            raise ValueError("codeEditor language must be a string")

        if len(v) > 2 and v[2] is not None and not isinstance(v[2], bool):
            raise ValueError("codeEditor readOnly must be a boolean")

        if len(v) > 3 and v[3] is not None:
            if not isinstance(v[3], list):
                raise ValueError("codeEditor highlightedLines must be an array")

            for line in v[3]:
                if not isinstance(line, int) or line < 1:
                    raise ValueError("codeEditor highlightedLines must be 1-based integers")

        if len(v) > 4:
            raise ValueError("codeEditor widget has too many elements")

        return v


class TreeViewWidget(BaseModel):
    """Tree View: [lesson, title?, textareaId?, editorId?]"""

    treeview: list[Any]

    @field_validator("treeview")
    @classmethod
    def validate_tv(cls, v: list[Any]) -> list[Any]:
        if not v:
            raise ValueError("treeview must have at least 1 element: [lesson]")

        # Heuristic: The AI often generates [Title, Content] instead of [Content, Title].
        # If v[0] is a string (Title like) and v[1] is a list (Tree content), swap them.
        if len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], list):
            # Swap to [Content, Title] to satisfy the schema explanation [lesson, title?]
            v = [v[1], v[0]]

        # v[0] is lesson object or string

        if len(v) > 1 and v[1] is not None and not isinstance(v[1], str):
            raise ValueError("treeview title must be a string")
        if len(v) > 2 and v[2] is not None and not isinstance(v[2], str):
            raise ValueError("treeview textarea_id must be a string")
        if len(v) > 3 and v[3] is not None and not isinstance(v[3], str):
            raise ValueError("treeview editor_id must be a string")

        return v


class MCQsQuestion(BaseModel):
    """MCQ question model."""

    q: StrictStr = Field(min_length=1)
    c: list[StrictStr] = Field(min_length=2)
    a: StrictInt
    e: StrictStr = Field(min_length=1)

    @field_validator("c")
    @classmethod
    def validate_choices(cls, v: list[str]) -> list[str]:
        if any(not c for c in v):
            raise ValueError("mcqs choices must be non-empty strings")
        return v

    @model_validator(mode="after")
    def validate_answer_index(self) -> MCQsQuestion:
        if not 0 <= self.a < len(self.c):
            raise ValueError("mcqs answer index must be within choices range")
        return self


class MCQsInner(BaseModel):
    title: StrictStr = Field(min_length=1)
    questions: list[MCQsQuestion] = Field(min_length=1)


class MCQsWidget(BaseModel):
    """MCQs widget: { "mcqs": { "title": ..., "questions": ... } }"""

    mcqs: MCQsInner


# --- Union Type ---

Widget = Union[
    StrictStr,  # Plain string is a paragraph
    ParagraphWidget,
    WarnWidget,
    ErrorWidget,
    SuccessWidget,
    FlipWidget,
    TranslationWidget,
    FillBlankWidget,
    UnorderedListWidget,
    OrderedListWidget,
    TableWidget,
    CompareWidget,
    SwipeCardsWidget,
    FreeTextWidget,
    InputLineWidget,
    StepFlowWidget,
    AsciiDiagramWidget,
    ChecklistWidget,
    InteractiveTerminalWidget,
    TerminalDemoWidget,
    CodeEditorWidget,
    TreeViewWidget,
    MCQsWidget,
]


def normalize_widget(widget: Any) -> dict[str, Any]:
    """
    Normalize a widget payload into canonical shorthand dict form.

    This keeps repair prompts and schema validation stable by converting
    shorthand inputs into explicit widget objects.
    """

    # Guard against missing payloads to keep downstream repair logic deterministic.
    if widget is None:
        raise ValueError("Widget payload cannot be None.")

    # Convert paragraph shorthand into the explicit widget object.
    if isinstance(widget, str):
        return {"p": widget}

    # Convert Pydantic models into their shorthand dict form.
    if isinstance(widget, BaseModel):
        # Prefer Pydantic v2's model_dump when available.
        dump = getattr(widget, "model_dump", None)

        # Use the Pydantic v2 path when present to preserve aliases.
        if callable(dump):
            return cast(dict[str, Any], dump(by_alias=True))

        return cast(dict[str, Any], widget.dict(by_alias=True))

    # Pass through mapping payloads that already resemble shorthand widgets.
    if isinstance(widget, dict):
        return widget

    # Reject unsupported widget payloads so callers can decide on fallbacks.
    raise ValueError("Widget payload must be a string or mapping.")


# --- Structure Models ---


class SubsectionBlock(BaseModel):
    """Subsection block."""

    subsection: str | None = None
    section: str | None = None
    items: list[Widget] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_title_field(self) -> SubsectionBlock:
        if not self.subsection and not self.section:
            raise ValueError("SubsectionBlock must have either 'subsection' or 'section' title")
        return self


class SectionBlock(BaseModel):
    """Section block."""

    section: StrictStr = Field(min_length=1)
    items: list[Widget] = Field(default_factory=list)
    subsections: list[SubsectionBlock] = Field(default_factory=list)


class LessonDocument(BaseModel):
    """Root lesson document."""

    title: StrictStr = Field(min_length=1)
    blocks: list[SectionBlock] = Field(default_factory=list)
