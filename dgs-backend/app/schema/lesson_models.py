"""Typed lesson schema models using positional array shorthands."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)


# --- Primitive Widgets ---

class ParagraphWidget(BaseModel):
    """Paragraph content widget."""
    p: StrictStr


class WarnWidget(BaseModel):
    """Warning callout."""
    warn: StrictStr


class ErrorWidget(BaseModel):
    """Error callout."""
    err: StrictStr


class SuccessWidget(BaseModel):
    """Success callout."""
    success: StrictStr


class FlipWidget(BaseModel):
    """Flipcard widget: [front, back, front_hint?, back_hint?]"""
    flip: list[StrictStr]

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

    @field_validator("tr")
    @classmethod
    def validate_tr(cls, v: list[str]) -> list[str]:
        if len(v) != 2:
            raise ValueError("tr widget must have exactly 2 elements: [source, target]")
        for item in v:
            if not re.match(r"^[A-Za-z]{2,3}[:-]", item):
                raise ValueError("translation entries must start with a language code (e.g. EN:)")
        return v


class BlankWidget(BaseModel):
    """Fill-in-the-blank widget: [prompt, answer, hint, explanation]"""
    blank: list[StrictStr]

    @field_validator("blank")
    @classmethod
    def validate_blank(cls, v: list[str]) -> list[str]:
        if len(v) != 4:
            raise ValueError("blank widget must have exactly 4 elements: [prompt, answer, hint, explanation]")
        if "___" not in v[0]:
            raise ValueError("blank prompt must include ___ placeholder")
        return v


class UnorderedListWidget(BaseModel):
    """Unordered list widget."""
    ul: list[StrictStr]


class OrderedListWidget(BaseModel):
    """Ordered list widget."""
    ol: list[StrictStr]


class TableWidget(BaseModel):
    """Tabular data widget."""
    table: list[list[StrictStr]]

    @field_validator("table")
    @classmethod
    def validate_rows(cls, v: list[list[str]]) -> list[list[str]]:
        if not v:
            raise ValueError("table requires at least one row")
        for row in v:
            if not row:
                raise ValueError("table rows must not be empty")
        return v


class CompareWidget(BaseModel):
    """Two-column comparison widget."""
    compare: list[list[StrictStr]]

    @field_validator("compare")
    @classmethod
    def validate_rows(cls, v: list[list[str]]) -> list[list[str]]:
        if not v:
            raise ValueError("compare requires at least one row")
        for row in v:
            if len(row) < 2:
                raise ValueError("compare rows must include at least two columns")
        return v


class SwipeWidget(BaseModel):
    """
    Swipe drill widget.
    Format: [title, [bucket1, bucket2], [[text, bucket_idx, feedback], ...]]
    """
    swipe: list[Any]

    @field_validator("swipe")
    @classmethod
    def validate_swipe(cls, v: list[Any]) -> list[Any]:
        if len(v) != 3:
            raise ValueError("swipe widget must have exactly 3 elements: [title, buckets, cards]")

        title, buckets, cards = v[0], v[1], v[2]

        if not isinstance(title, str) or not title:
            raise ValueError("swipe title must be a non-empty string")

        if not isinstance(buckets, list) or len(buckets) != 2 or not all(isinstance(b, str) and b for b in buckets):
            raise ValueError("swipe buckets must be a list of two non-empty strings")

        if not isinstance(cards, list) or not cards:
            raise ValueError("swipe cards must be a non-empty list")

        for i, card in enumerate(cards):
            if not isinstance(card, list) or len(card) != 3:
                raise ValueError(f"swipe card at index {i} must be [text, correct_bucket_idx, feedback]")
            text, idx, feedback = card
            if not isinstance(text, str):
                raise ValueError(f"swipe card {i} text must be a string")
            if not isinstance(idx, int) or idx not in (0, 1):
                raise ValueError(f"swipe card {i} correct_bucket_idx must be 0 or 1")
            if not isinstance(feedback, str):
                raise ValueError(f"swipe card {i} feedback must be a string")

            if len(text) > 120:
                raise ValueError(f"swipe card {i} text exceeds 120 characters")
            if len(feedback) > 150:
                raise ValueError(f"swipe card {i} feedback exceeds 150 characters")

        return v


class FreeTextWidget(BaseModel):
    """
    Free text editor widget.
    Format: [prompt, seed_locked?, text?, lang?, wordlist_csv?, mode?]
    """
    freeText: list[Any]

    @field_validator("freeText")
    @classmethod
    def validate_free_text(cls, v: list[Any]) -> list[Any]:
        if len(v) < 1:
            raise ValueError("freeText widget must have at least a prompt")

        # 0: prompt
        if not isinstance(v[0], str):
            raise ValueError("freeText prompt must be a string")

        # 1: seed_locked (optional)
        if len(v) > 1 and v[1] is not None and not isinstance(v[1], str):
            raise ValueError("freeText seed_locked must be a string or null")

        # 2: text (optional)
        if len(v) > 2 and v[2] is not None and not isinstance(v[2], str):
             raise ValueError("freeText text must be a string or null")

        # 3: lang (optional)
        if len(v) > 3 and v[3] is not None and not isinstance(v[3], str):
             raise ValueError("freeText lang must be a string or null")

        # 4: wordlist_csv (optional)
        if len(v) > 4 and v[4] is not None and not isinstance(v[4], str):
             raise ValueError("freeText wordlist_csv must be a string or null")

        # 5: mode (optional)
        if len(v) > 5 and v[5] is not None:
            if v[5] not in ("single", "multi"):
                 raise ValueError("freeText mode must be 'single' or 'multi'")

        return v


class StepFlowWidget(BaseModel):
    """
    Step-by-step flow.
    Format: [lead, flow]
    flow is a list where items are strings or branch nodes: [[label, steps], ...]
    """
    stepFlow: list[Any]

    @field_validator("stepFlow")
    @classmethod
    def validate_step_flow(cls, v: list[Any]) -> list[Any]:
        if len(v) != 2:
            raise ValueError("stepFlow must have exactly 2 elements: [lead, flow]")

        lead, flow = v[0], v[1]
        if not isinstance(lead, str) or not lead:
             raise ValueError("stepFlow lead must be a non-empty string")
        if not isinstance(flow, list) or not flow:
             raise ValueError("stepFlow flow must be a non-empty list")

        cls._validate_flow_nodes(flow, depth=0)
        return v

    @classmethod
    def _validate_flow_nodes(cls, nodes: list[Any], depth: int):
        if depth > 5:
            raise ValueError("stepFlow nesting depth exceeded (max 5)")

        for node in nodes:
            if isinstance(node, str):
                continue
            elif isinstance(node, list):
                # Branch node: list of options. Each option is [label, steps]
                if not node:
                     raise ValueError("stepFlow branch node cannot be empty")

                for option in node:
                    if not isinstance(option, list) or len(option) != 2:
                        raise ValueError("stepFlow branch option must be [label, steps]")
                    label, steps = option
                    if not isinstance(label, str):
                        raise ValueError("stepFlow branch label must be a string")
                    if not isinstance(steps, list):
                        raise ValueError("stepFlow branch steps must be a list")

                    cls._validate_flow_nodes(steps, depth + 1)
            else:
                raise ValueError("stepFlow node must be a string or a branch list")


class AsciiDiagramWidget(BaseModel):
    """Ascii Diagram: [lead, diagram]"""
    asciiDiagram: list[StrictStr]

    @field_validator("asciiDiagram")
    @classmethod
    def validate_diagram(cls, v: list[str]) -> list[str]:
        if len(v) != 2:
             raise ValueError("asciiDiagram must have exactly 2 elements: [lead, diagram]")
        return v


class ChecklistWidget(BaseModel):
    """
    Checklist: [lead, tree]
    tree items are strings or groups: [title, children]
    """
    checklist: list[Any]

    @field_validator("checklist")
    @classmethod
    def validate_checklist(cls, v: list[Any]) -> list[Any]:
        if len(v) != 2:
            raise ValueError("checklist must have exactly 2 elements: [lead, tree]")

        lead, tree = v[0], v[1]
        if not isinstance(lead, str):
            raise ValueError("checklist lead must be a string")
        if not isinstance(tree, list) or not tree:
            raise ValueError("checklist tree must be a non-empty list")

        cls._validate_tree(tree, depth=1)
        return v

    @classmethod
    def _validate_tree(cls, nodes: list[Any], depth: int):
        if depth > 3:
            raise ValueError("checklist nesting depth exceeded (max 3)")

        for node in nodes:
            if isinstance(node, str):
                continue
            elif isinstance(node, list):
                if len(node) != 2:
                    raise ValueError("checklist group must be [title, children]")
                title, children = node
                if not isinstance(title, str):
                     raise ValueError("checklist group title must be a string")
                if not isinstance(children, list):
                     raise ValueError("checklist group children must be a list")

                cls._validate_tree(children, depth + 1)
            else:
                 raise ValueError("checklist node must be a string or [title, children]")


class ConsoleWidget(BaseModel):
    """
    Console/Terminal: [lead, mode, rules_or_script, guided?]
    mode: 0 (demo) or 1 (interactive)
    """
    console: list[Any]

    @field_validator("console")
    @classmethod
    def validate_console(cls, v: list[Any]) -> list[Any]:
        if len(v) < 3:
             raise ValueError("console widget must have at least 3 elements: [lead, mode, rules_or_script]")

        lead, mode, content = v[0], v[1], v[2]
        guided = v[3] if len(v) > 3 else None

        if not isinstance(lead, str):
            raise ValueError("console lead must be a string")
        if mode not in (0, 1):
            raise ValueError("console mode must be 0 (demo) or 1 (interactive)")
        if not isinstance(content, list):
            raise ValueError("console rules_or_script must be a list")

        if mode == 0:
            # Demo mode: [command, delay, output]
            for entry in content:
                if not isinstance(entry, list) or len(entry) != 3:
                     raise ValueError("console demo entry must be [command, delay_ms, output]")
                if not isinstance(entry[0], str) or not isinstance(entry[1], int) or not isinstance(entry[2], str):
                     raise ValueError("console demo entry types must be [str, int, str]")
        else:
            # Interactive: [regex, level, output]
            for entry in content:
                if not isinstance(entry, list) or len(entry) != 3:
                     raise ValueError("console interactive rule must be [pattern, level, output]")
                if not isinstance(entry[0], str) or not isinstance(entry[1], str) or not isinstance(entry[2], str):
                     raise ValueError("console interactive rule types must be [str, str, str]")

        if guided is not None:
             if not isinstance(guided, list):
                  raise ValueError("console guided steps must be a list")
             for step in guided:
                  if not isinstance(step, list) or len(step) != 2:
                       raise ValueError("console guided step must be [task, solution]")
                  if not isinstance(step[0], str) or not isinstance(step[1], str):
                       raise ValueError("console guided step elements must be strings")

        return v


class CodeViewerWidget(BaseModel):
    """Code Viewer: [code, language, editable?, textareaId?]"""
    codeviewer: list[Any]

    @field_validator("codeviewer")
    @classmethod
    def validate_cv(cls, v: list[Any]) -> list[Any]:
        if len(v) < 2:
             raise ValueError("codeviewer must have at least 2 elements: [code, language]")

        code, lang = v[0], v[1]
        if not isinstance(code, (str, dict, list)): # code can be object if json
             # The old model said StrictStr, but users might pass json object which gets stringified?
             # widgets.md says: code (string|object): code to display; objects are JSON-stringified.
             pass

        if not isinstance(lang, str):
             raise ValueError("codeviewer language must be a string")

        if len(v) > 2 and v[2] is not None and not isinstance(v[2], bool):
             raise ValueError("codeviewer editable must be a boolean")

        if len(v) > 3 and v[3] is not None and not isinstance(v[3], str):
             raise ValueError("codeviewer textarea_id must be a string")

        return v


class TreeViewWidget(BaseModel):
    """Tree View: [lesson, title?, textareaId?, editorId?]"""
    treeview: list[Any]

    @field_validator("treeview")
    @classmethod
    def validate_tv(cls, v: list[Any]) -> list[Any]:
        if not v:
             raise ValueError("treeview must have at least 1 element: [lesson]")

        # v[0] is lesson object or string

        if len(v) > 1 and v[1] is not None and not isinstance(v[1], str):
             raise ValueError("treeview title must be a string")
        if len(v) > 2 and v[2] is not None and not isinstance(v[2], str):
             raise ValueError("treeview textarea_id must be a string")
        if len(v) > 3 and v[3] is not None and not isinstance(v[3], str):
             raise ValueError("treeview editor_id must be a string")

        return v


class QuizQuestion(BaseModel):
    """Quiz question model (remains object-based inside the quiz widget)."""
    q: StrictStr = Field(min_length=1)
    c: list[StrictStr] = Field(min_length=2)
    a: StrictInt
    e: StrictStr = Field(min_length=1)

    @field_validator("c")
    @classmethod
    def validate_choices(cls, v: list[str]) -> list[str]:
        if any(not c for c in v):
            raise ValueError("quiz choices must be non-empty strings")
        return v

    @model_validator(mode="after")
    def validate_answer_index(self) -> QuizQuestion:
        if not 0 <= self.a < len(self.c):
            raise ValueError("quiz answer index must be within choices range")
        return self


class QuizInner(BaseModel):
    title: StrictStr = Field(min_length=1)
    questions: list[QuizQuestion] = Field(min_length=1)


class QuizWidget(BaseModel):
    """Quiz widget: { "quiz": { "title": ..., "questions": ... } }"""
    quiz: QuizInner


# --- Union Type ---

Widget = Union[
    StrictStr,  # Plain string is a paragraph
    ParagraphWidget,
    WarnWidget,
    ErrorWidget,
    SuccessWidget,
    FlipWidget,
    TranslationWidget,
    BlankWidget,
    UnorderedListWidget,
    OrderedListWidget,
    TableWidget,
    CompareWidget,
    SwipeWidget,
    FreeTextWidget,
    StepFlowWidget,
    AsciiDiagramWidget,
    ChecklistWidget,
    ConsoleWidget,
    CodeViewerWidget,
    TreeViewWidget,
    QuizWidget,
]


# --- Structure Models ---

class SubsectionBlock(BaseModel):
    """Subsection block."""
    subsection: StrictStr = Field(min_length=1)
    items: list[Widget] = Field(default_factory=list)


class SectionBlock(BaseModel):
    """Section block."""
    section: StrictStr = Field(min_length=1)
    items: list[Widget] = Field(default_factory=list)
    subsections: list[SubsectionBlock] = Field(default_factory=list)


class LessonDocument(BaseModel):
    """Root lesson document."""
    title: StrictStr = Field(min_length=1)
    blocks: list[SectionBlock] = Field(default_factory=list)

