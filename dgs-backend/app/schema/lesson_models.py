"""Typed lesson schema models with strict validation."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class LessonBaseModel(BaseModel):
    """Base model enforcing strict field handling."""

    # model_config = ConfigDict(extra="forbid", populate_by_name=True)
    type: StrictStr


class WidgetBase(LessonBaseModel):
    """Base class for all widgets."""




class ParagraphWidget(WidgetBase):
    """Paragraph content widget."""

    type: Literal["p"]
    text: StrictStr


class CalloutWidget(WidgetBase):
    """Callout variants for inline emphasis."""

    type: Literal["info", "tip", "warn", "err", "success"]
    text: StrictStr


class FlipWidget(WidgetBase):
    """Flipcard widget with optional hints."""

    type: Literal["flip"]
    front: StrictStr = Field(min_length=1, max_length=120)
    back: StrictStr = Field(min_length=1, max_length=160)
    front_hint: StrictStr | None = None
    back_hint: StrictStr | None = None


class TranslationWidget(WidgetBase):
    """Translation pair widget."""

    type: Literal["tr"]
    source: StrictStr = Field(min_length=1)
    target: StrictStr = Field(min_length=1)

    @field_validator("source", "target")
    @classmethod
    def validate_language_prefix(cls, value: StrictStr) -> StrictStr:
        if not re.match(r"^[A-Za-z]{2,3}[:-]", value):
            raise ValueError("translation entries must start with a language code (e.g. EN:)")
        return value


class BlankWidget(WidgetBase):
    """Fill-in-the-blank widget."""

    type: Literal["blank"]
    prompt: StrictStr = Field(min_length=1)
    answer: StrictStr = Field(min_length=1)
    hint: StrictStr = Field(min_length=1)
    explanation: StrictStr = Field(min_length=1)

    @field_validator("prompt")
    @classmethod
    def validate_prompt_placeholder(cls, value: StrictStr) -> StrictStr:
        if "___" not in value:
            raise ValueError("blank prompt must include ___ placeholder")
        return value


class ListWidget(WidgetBase):
    """Ordered or unordered list widget."""

    type: Literal["ul", "ol"]
    items: list[StrictStr]


class TableWidget(WidgetBase):
    """Tabular data widget."""

    type: Literal["table"]
    rows: list[list[StrictStr]]

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, value: list[list[StrictStr]]) -> list[list[StrictStr]]:
        if not value:
            raise ValueError("table requires at least one row")
        for row in value:
            if not row:
                raise ValueError("table rows must not be empty")
        return value


class CompareWidget(WidgetBase):
    """Two-column comparison widget."""

    type: Literal["compare"]
    rows: list[list[StrictStr]]

    @field_validator("rows")
    @classmethod
    def validate_rows(cls, value: list[list[StrictStr]]) -> list[list[StrictStr]]:
        if not value:
            raise ValueError("compare requires at least one row")
        for row in value:
            if len(row) < 2:
                raise ValueError("compare rows must include two columns")
        return value


class SwipeCard(LessonBaseModel):
    """Card entry for swipe widget."""

    text: StrictStr = Field(min_length=1, max_length=120)
    correct_bucket: Literal[0, 1]
    feedback: StrictStr = Field(min_length=1, max_length=150)


class SwipeWidget(WidgetBase):
    """Binary swipe drill widget."""

    type: Literal["swipe"]
    title: StrictStr = Field(min_length=1)
    buckets: list[StrictStr]
    cards: list[SwipeCard]

    @field_validator("buckets")
    @classmethod
    def validate_buckets(cls, value: list[StrictStr]) -> list[StrictStr]:
        if len(value) != 2:
            raise ValueError("swipe buckets must contain exactly two labels")
        if any(not label for label in value):
            raise ValueError("swipe bucket labels must be non-empty")
        return value

    @field_validator("cards")
    @classmethod
    def validate_cards(cls, value: list[SwipeCard]) -> list[SwipeCard]:
        if not value:
            raise ValueError("swipe requires at least one card")
        return value


class FreeTextWidget(WidgetBase):
    """Free text editor widget."""

    type: Literal["freeText"]
    prompt: StrictStr = Field(min_length=1)
    seed_locked: StrictStr | None = None
    text: StrictStr
    lang: StrictStr = "en"
    wordlist_csv: StrictStr | None = None
    mode: Literal["single", "multi"] = "multi"


FlowNode = Union[StrictStr, "StepFlowBranch"]


class StepFlowOption(LessonBaseModel):
    """Branch option for step flow."""

    label: StrictStr = Field(min_length=1)
    steps: list[FlowNode]


class StepFlowBranch(LessonBaseModel):
    """Branching node in a step flow."""

    options: list[StepFlowOption]

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[StepFlowOption]) -> list[StepFlowOption]:
        if not value:
            raise ValueError("stepFlow branch must include at least one option")
        return value


class StepFlowWidget(WidgetBase):
    """Step-by-step flow widget with optional branching."""

    type: Literal["stepFlow"]
    lead: StrictStr = Field(min_length=1)
    flow: list[FlowNode]

    @field_validator("flow")
    @classmethod
    def validate_flow(cls, value: list[FlowNode]) -> list[FlowNode]:
        if not value:
            raise ValueError("stepFlow requires at least one flow entry")
        return value

    @field_validator("flow")
    @classmethod
    def validate_branching_depth(cls, value: list[FlowNode]) -> list[FlowNode]:
        def max_branch_depth(nodes: list[FlowNode], depth: int = 1) -> int:
            max_depth = depth
            for node in nodes:
                if isinstance(node, StepFlowBranch):
                    for option in node.options:
                        max_depth = max(max_depth, max_branch_depth(option.steps, depth + 1))
            return max_depth

        if max_branch_depth(value) > 5:
            raise ValueError("stepFlow branching depth must be 5 or less")
        return value


class AsciiDiagramWidget(WidgetBase):
    """ASCII diagram widget."""

    type: Literal["asciiDiagram"]
    lead: StrictStr
    diagram: StrictStr


ChecklistNode = Union[StrictStr, "ChecklistGroup"]


class ChecklistGroup(LessonBaseModel):
    """Nested checklist group."""

    title: StrictStr = Field(min_length=1)
    children: list[ChecklistNode]

    @field_validator("children")
    @classmethod
    def validate_children(cls, value: list[ChecklistNode]) -> list[ChecklistNode]:
        if not value:
            raise ValueError("checklist group must include children")
        return value


class ChecklistWidget(WidgetBase):
    """Nested checklist widget."""

    type: Literal["checklist"]
    lead: StrictStr = Field(min_length=1)
    tree: list[ChecklistNode]

    @field_validator("tree")
    @classmethod
    def validate_tree(cls, value: list[ChecklistNode]) -> list[ChecklistNode]:
        if not value:
            raise ValueError("checklist requires at least one node")
        return value

    @field_validator("tree")
    @classmethod
    def validate_nesting_depth(cls, value: list[ChecklistNode]) -> list[ChecklistNode]:
        def max_depth(nodes: list[ChecklistNode], depth: int = 1) -> int:
            max_seen = depth
            for node in nodes:
                if isinstance(node, ChecklistGroup):
                    max_seen = max(max_seen, max_depth(node.children, depth + 1))
            return max_seen

        if max_depth(value) > 3:
            raise ValueError("checklist nesting depth must be 3 or less")
        return value


class ConsoleDemoEntry(LessonBaseModel):
    """Scripted console entry for demo mode."""

    command: StrictStr
    delay_ms: StrictInt
    output: StrictStr


class ConsoleInteractiveRule(LessonBaseModel):
    """Interactive console rule for validation."""

    pattern: StrictStr
    level: StrictStr
    output: StrictStr


class ConsoleGuidedStep(LessonBaseModel):
    """Guided step for interactive console."""

    task: StrictStr
    solution: StrictStr


class ConsoleWidget(WidgetBase):
    """Terminal simulator widget."""

    type: Literal["console"]
    lead: StrictStr
    mode: Literal[0, 1]
    rules_or_script: list[ConsoleDemoEntry | ConsoleInteractiveRule]
    guided: list[ConsoleGuidedStep] = Field(default_factory=list)

    @field_validator("rules_or_script")
    @classmethod
    def validate_rules(
        cls,
        value: list[ConsoleDemoEntry | ConsoleInteractiveRule],
        values: dict[str, Any] | Any,
    ) -> list[ConsoleDemoEntry | ConsoleInteractiveRule]:
        mode: int | None = None
        if hasattr(values, "data"):
            data = getattr(values, "data", {}) or {}
            mode = data.get("mode")
        elif isinstance(values, dict):
            mode = values.get("mode")
        if mode == 0:
            if not all(isinstance(item, ConsoleDemoEntry) for item in value):
                raise ValueError("console mode 0 requires demo script entries")
        elif mode == 1:
            if not all(isinstance(item, ConsoleInteractiveRule) for item in value):
                raise ValueError("console mode 1 requires interactive rules")
        else:
            raise ValueError("console mode must be 0 or 1")
        if not value:
            raise ValueError("console requires at least one rule or script entry")
        return value


class CodeViewerWidget(WidgetBase):
    """Code viewer/editor widget."""

    type: Literal["codeviewer"]
    code: StrictStr
    language: StrictStr = Field(min_length=1)
    editable: StrictBool = False
    textarea_id: StrictStr | None = None


class TreeViewWidget(WidgetBase):
    """Lesson structure viewer widget."""

    type: Literal["treeview"]
    lesson: StrictStr
    title: StrictStr | None = None
    textarea_id: StrictStr | None = None
    editor_id: StrictStr | None = None


class QuizQuestion(LessonBaseModel):
    """Quiz question model."""

    prompt: StrictStr = Field(..., alias="q", min_length=1)
    choices: list[StrictStr] = Field(..., alias="c")
    answer_index: StrictInt = Field(..., alias="a")
    explanation: StrictStr = Field(..., alias="e", min_length=1)

    @field_validator("choices")
    @classmethod
    def validate_choices(cls, value: list[StrictStr]) -> list[StrictStr]:
        if len(value) < 2:
            raise ValueError("quiz choices must include at least two options")
        if any(not choice for choice in value):
            raise ValueError("quiz choices must be non-empty strings")
        return value

    @model_validator(mode="after")
    def validate_answer_index(self) -> QuizQuestion:
        if not 0 <= self.answer_index < len(self.choices):
            raise ValueError("quiz answer index must be within choices range")
        return self


class QuizWidget(WidgetBase):
    """Multiple-choice quiz widget."""

    type: Literal["quiz"]
    title: StrictStr = Field(min_length=1)
    questions: list[QuizQuestion]

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, value: list[QuizQuestion]) -> list[QuizQuestion]:
        if not value:
            raise ValueError("quiz requires at least one question")
        return value


# Widget = Annotated[
#     ParagraphWidget
#     | CalloutWidget
#     # | BlankWidget
#     # | ListWidget
#     # | TableWidget
#     # | CompareWidget
#     # | SwipeWidget
#     # | FreeTextWidget
#     # | StepFlowWidget
#     # | AsciiDiagramWidget
#     # | ChecklistWidget
#     # | ConsoleWidget
#     # | CodeViewerWidget
#     # | TreeViewWidget
#     # | QuizWidget
#     ,
#     Field(discriminator="type")
# ]


class SectionBlock(LessonBaseModel):
    """Primary section block containing content widgets."""

    section: StrictStr = Field(min_length=1)
    items: list[WidgetBase] = Field(default_factory=list)
    subsections: list[SubsectionBlock] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_items(cls, data: Any) -> Any:
        raw_items = data.get("items") if isinstance(data, dict) else None
        if raw_items is None:
            return data
        data = dict(data)
        data["items"] = [normalize_widget(item) for item in raw_items]
        return data

class SubsectionBlock(LessonBaseModel):
    """Primary subsection block containing content widgets."""

    subsection: StrictStr = Field(min_length=1)
    items: list[WidgetBase] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_items(cls, data: Any) -> Any:
        raw_items = data.get("items") if isinstance(data, dict) else None
        if raw_items is None:
            return data
        data = dict(data)
        data["items"] = [normalize_widget(item) for item in raw_items]
        return data


class LessonDocument(LessonBaseModel):
    """Versioned root lesson document."""

    title: StrictStr = Field(min_length=1)
    blocks: list[SectionBlock]

def _normalize_callout(value: Any, widget_type: str) -> dict[str, Any]:
    if not isinstance(value, str):
        raise ValueError(f"{widget_type} widget expects a string message")
    return {"type": widget_type, "text": value}


def _normalize_list(value: Any, widget_type: str) -> dict[str, Any]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{widget_type} widget expects a list of strings")
    return {"type": widget_type, "items": value}


def _normalize_flip(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("flip widget expects at least front and back text")
    front, back = value[0], value[1]
    if not isinstance(front, str) or not isinstance(back, str):
        raise ValueError("flip widget requires string front/back")
    front_hint = value[2] if len(value) > 2 else None
    back_hint = value[3] if len(value) > 3 else None
    return {
        "type": "flip",
        "front": front,
        "back": back,
        "front_hint": front_hint,
        "back_hint": back_hint,
    }


def _normalize_tr(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, str) for item in value)
    ):
        raise ValueError("tr widget expects two translation strings")
    return {"type": "tr", "source": value[0], "target": value[1]}


def _normalize_blank(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or not all(isinstance(item, str) for item in value)
    ):
        raise ValueError("blank widget expects four strings: prompt, answer, hint, explanation")
    prompt, answer, hint, explanation = value
    return {
        "type": "blank",
        "prompt": prompt,
        "answer": answer,
        "hint": hint,
        "explanation": explanation,
    }


def _normalize_table(value: Any, widget_type: str) -> dict[str, Any]:
    if not isinstance(value, list) or not all(isinstance(row, list) for row in value):
        raise ValueError(f"{widget_type} widget expects a list of rows")
    for row in value:
        if not all(isinstance(cell, str) for cell in row):
            raise ValueError(f"{widget_type} rows must contain only strings")
    field_name = "rows" if widget_type in {"table", "compare"} else "items"
    return {"type": widget_type, field_name: value}


def _normalize_swipe(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) < 3:
        raise ValueError("swipe widget expects [title, buckets, cards]")
    title, buckets, cards = value[0], value[1], value[2]
    if not isinstance(title, str):
        raise ValueError("swipe title must be a string")
    if (
        not isinstance(buckets, list)
        or len(buckets) != 2
        or not all(isinstance(b, str) for b in buckets)
    ):
        raise ValueError("swipe buckets must be a list of two strings")
    if not isinstance(cards, list):
        raise ValueError("swipe cards must be a list")
    normalized_cards: list[dict[str, Any]] = []
    for entry in cards:
        if not (isinstance(entry, list) and len(entry) >= 3):
            raise ValueError("each swipe card must be [text, correctBucket, feedback]")
        text, correct_bucket, feedback = entry[0], entry[1], entry[2]
        if (
            not isinstance(text, str)
            or not isinstance(correct_bucket, int)
            or not isinstance(feedback, str)
        ):
            raise ValueError("swipe card values must be [str, int, str]")
        normalized_cards.append(
            {"text": text, "correct_bucket": int(correct_bucket), "feedback": feedback}
        )
    return {"type": "swipe", "title": title, "buckets": buckets, "cards": normalized_cards}


def _normalize_free_text(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) < 1:
        raise ValueError("freeText widget expects at least a prompt entry")
    prompt = value[0]
    if not isinstance(prompt, str):
        raise ValueError("freeText prompt must be a string")
    seed_locked = value[1] if len(value) > 1 else None
    text = value[2] if len(value) > 2 else ""
    lang = value[3] if len(value) > 3 else "en"
    wordlist_csv = value[4] if len(value) > 4 else None
    mode = value[5] if len(value) > 5 else "multi"
    return {
        "type": "freeText",
        "prompt": prompt,
        "seed_locked": seed_locked,
        "text": text if isinstance(text, str) else str(text),
        "lang": lang if isinstance(lang, str) else "en",
        "wordlist_csv": wordlist_csv if isinstance(wordlist_csv, str) else None,
        "mode": mode if isinstance(mode, str) else "multi",
    }


def _normalize_step_flow(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("stepFlow widget expects [lead, flow]")
    lead, flow = value[0], value[1]
    if not isinstance(lead, str):
        raise ValueError("stepFlow lead must be a string")
    if not isinstance(flow, list):
        raise ValueError("stepFlow flow must be a list")

    def normalize_node(node: Any) -> StrictStr | dict[str, Any]:
        if isinstance(node, str):
            return node
        if isinstance(node, list):
            options: list[dict[str, Any]] = []
            for opt in node:
                if not (isinstance(opt, list) and len(opt) == 2):
                    raise ValueError("stepFlow branch option must be [label, steps]")
                label, steps = opt
                if not isinstance(label, str) or not isinstance(steps, list):
                    raise ValueError("stepFlow option requires string label and list of steps")
                options.append({"label": label, "steps": [normalize_node(s) for s in steps]})
            return {"options": options}
        raise ValueError("stepFlow nodes must be strings or branch option lists")

    normalized_flow = [normalize_node(item) for item in flow]
    return {"type": "stepFlow", "lead": lead, "flow": normalized_flow}


def _normalize_ascii_diagram(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("asciiDiagram widget expects [lead, diagram]")
    lead, diagram = value
    if not isinstance(lead, str) or not isinstance(diagram, str):
        raise ValueError("asciiDiagram values must be strings")
    return {"type": "asciiDiagram", "lead": lead, "diagram": diagram}


def _normalize_checklist(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("checklist widget expects [lead, tree]")
    lead, tree = value
    if not isinstance(lead, str) or not isinstance(tree, list):
        raise ValueError("checklist requires a string lead and list tree")

    def normalize_node(node: Any) -> StrictStr | dict[str, Any]:
        if isinstance(node, str):
            return node
        if isinstance(node, list) and len(node) == 2:
            title, children = node
            if not isinstance(title, str) or not isinstance(children, list):
                raise ValueError("checklist group requires string title and list of children")
            return {"title": title, "children": [normalize_node(child) for child in children]}
        raise ValueError("checklist node must be a string or [title, children]")

    normalized_tree = [normalize_node(entry) for entry in tree]
    return {"type": "checklist", "lead": lead, "tree": normalized_tree}


def _normalize_console(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) < 3:
        raise ValueError("console widget expects [lead, mode, rulesOrScript, guided?]")
    lead, mode, rules_or_script = value[0], value[1], value[2]
    guided = value[3] if len(value) > 3 else None
    if not isinstance(lead, str):
        raise ValueError("console lead must be a string")
    if not isinstance(mode, int) or mode not in (0, 1):
        raise ValueError("console mode must be 0 or 1")
    if not isinstance(rules_or_script, list):
        raise ValueError("console rulesOrScript must be a list")

    normalized_entries: list[dict[str, Any]] = []
    if mode == 0:
        for entry in rules_or_script:
            if not (isinstance(entry, list) and len(entry) == 3):
                raise ValueError("console demo entries must be [command, delayMs, output]")
            command, delay_ms, output = entry
            if (
                not isinstance(command, str)
                or not isinstance(delay_ms, int)
                or not isinstance(output, str)
            ):
                raise ValueError("console demo entry types must be [str, int, str]")
            normalized_entries.append({"command": command, "delay_ms": delay_ms, "output": output})
    else:
        for entry in rules_or_script:
            if not (isinstance(entry, list) and len(entry) == 3):
                raise ValueError("console interactive rules must be [regex, level, output]")
            pattern, level, output = entry
            if (
                not isinstance(pattern, str)
                or not isinstance(level, str)
                or not isinstance(output, str)
            ):
                raise ValueError("console interactive rule types must be [str, str, str]")
            normalized_entries.append({"pattern": pattern, "level": level, "output": output})

    normalized_guided: list[dict[str, Any]] | None = None
    if guided is not None:
        if not isinstance(guided, list):
            raise ValueError("console guided steps must be a list")
        normalized_guided = []
        for entry in guided:
            if not (isinstance(entry, list) and len(entry) == 2):
                raise ValueError("console guided steps must be [task, solution]")
            task, solution = entry
            if not isinstance(task, str) or not isinstance(solution, str):
                raise ValueError("console guided step entries must be strings")
            normalized_guided.append({"task": task, "solution": solution})

    return {
        "type": "console",
        "lead": lead,
        "mode": mode,
        "rules_or_script": normalized_entries,
        "guided": normalized_guided,
    }


def _normalize_codeviewer(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("codeviewer widget expects [code, language, editable?, textareaId?]")
    code, language = value[0], value[1]
    editable = value[2] if len(value) > 2 else False
    textarea_id = value[3] if len(value) > 3 else None
    if not isinstance(language, str):
        raise ValueError("codeviewer language must be a string")
    if editable is not None and not isinstance(editable, bool):
        raise ValueError("codeviewer editable must be a boolean when provided")
    if textarea_id is not None and not isinstance(textarea_id, str):
        raise ValueError("codeviewer textareaId must be a string when provided")
    return {
        "type": "codeviewer",
        "code": code,
        "language": language,
        "editable": bool(editable),
        "textarea_id": textarea_id,
    }


def _normalize_treeview(value: Any) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) < 1:
        raise ValueError("treeview widget expects [lesson, title?, textareaId?, editorId?]")
    lesson = value[0]
    title = value[1] if len(value) > 1 else None
    textarea_id = value[2] if len(value) > 2 else None
    editor_id = value[3] if len(value) > 3 else None
    if title is not None and not isinstance(title, str):
        raise ValueError("treeview title must be a string when provided")
    if textarea_id is not None and not isinstance(textarea_id, str):
        raise ValueError("treeview textareaId must be a string when provided")
    if editor_id is not None and not isinstance(editor_id, str):
        raise ValueError("treeview editorId must be a string when provided")
    return {
        "type": "treeview",
        "lesson": lesson,
        "title": title,
        "textarea_id": textarea_id,
        "editor_id": editor_id,
    }


def _normalize_quiz(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("quiz widget expects an object with title and questions")
    title = value.get("title")
    questions = value.get("questions")
    if not isinstance(title, str) or not isinstance(questions, list):
        raise ValueError("quiz widget requires string title and list of questions")
    normalized_questions: list[dict[str, Any]] = []
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError("quiz questions must be objects")
        normalized_questions.append(question)
    return {"type": "quiz", "title": title, "questions": normalized_questions}


_NORMALIZERS = {
    "p": lambda value: {"type": "p", "text": value} if isinstance(value, str) else None,
    "info": lambda value: _normalize_callout(value, "info"),
    "tip": lambda value: _normalize_callout(value, "tip"),
    "warn": lambda value: _normalize_callout(value, "warn"),
    "err": lambda value: _normalize_callout(value, "err"),
    "success": lambda value: _normalize_callout(value, "success"),
    "flip": _normalize_flip,
    "tr": _normalize_tr,
    "blank": _normalize_blank,
    "ul": lambda value: _normalize_list(value, "ul"),
    "ol": lambda value: _normalize_list(value, "ol"),
    "table": lambda value: _normalize_table(value, "table"),
    "compare": lambda value: _normalize_table(value, "compare"),
    "swipe": _normalize_swipe,
    "freeText": _normalize_free_text,
    "stepFlow": _normalize_step_flow,
    "asciiDiagram": _normalize_ascii_diagram,
    "checklist": _normalize_checklist,
    "console": _normalize_console,
    "codeviewer": _normalize_codeviewer,
    "treeview": _normalize_treeview,
    "quiz": _normalize_quiz,
}


def normalize_widget(entry: Any) -> dict[str, Any]:
    """Normalize shorthand widget syntax into discriminated form."""

    if isinstance(entry, str):
        return {"type": "p", "text": entry}

    if not isinstance(entry, dict):
        raise ValueError("widget must be a string or object")

    if "type" in entry:
        return entry

    if len(entry) != 1:
        raise ValueError("widget objects must include exactly one key")

    key, value = next(iter(entry.items()))
    normalizer = _NORMALIZERS.get(str(key))
    if normalizer is None:
        raise ValueError(f"unsupported widget type: {key}")

    normalized = normalizer(value)
    if normalized is None:
        raise ValueError(f"invalid widget payload for {key}")
    return normalized


SectionBlock.update_forward_refs()
StepFlowBranch.update_forward_refs()
StepFlowOption.update_forward_refs()
ChecklistGroup.update_forward_refs()
ChecklistWidget.update_forward_refs()
StepFlowWidget.update_forward_refs()
LessonDocument.update_forward_refs()
