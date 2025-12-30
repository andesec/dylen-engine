"""Serialize lesson models into the shorthand widget format."""

from __future__ import annotations

from typing import Any, cast

from .lesson_models import (
    AsciiDiagramWidget,
    BlankWidget,
    CalloutWidget,
    ChecklistGroup,
    ChecklistWidget,
    CodeViewerWidget,
    CompareWidget,
    ConsoleWidget,
    FlipWidget,
    FreeTextWidget,
    LessonDocument,
    ListWidget,
    ParagraphWidget,
    QuizQuestion,
    QuizWidget,
    SectionBlock,
    StepFlowBranch,
    StepFlowOption,
    StepFlowWidget,
    SwipeWidget,
    TableWidget,
    TranslationWidget,
    TreeViewWidget,
    Widget,
)


def _dump_model(model: Any, *, by_alias: bool = False) -> dict[str, Any]:
    dump = getattr(model, "model_dump", None)
    if callable(dump):
        return cast(dict[str, Any], dump(by_alias=by_alias))
    return cast(dict[str, Any], model.dict(by_alias=by_alias))


def _trim_trailing(values: list[Any], default_map: dict[int, Any] | None = None) -> list[Any]:
    trimmed = list(values)
    while trimmed:
        idx = len(trimmed) - 1
        val = trimmed[idx]
        default = default_map.get(idx) if default_map else None
        if val is None or val == default:
            trimmed.pop()
            continue
        break
    return trimmed


def _step_flow_node_to_shorthand(node: Any) -> Any:
    if isinstance(node, StepFlowBranch):
        return [
            [option.label, [_step_flow_node_to_shorthand(s) for s in option.steps]]
            for option in node.options
        ]
    if isinstance(node, str):
        return node
    if isinstance(node, StepFlowOption):
        return [node.label, [_step_flow_node_to_shorthand(s) for s in node.steps]]
    return node


def _checklist_node_to_shorthand(node: Any) -> Any:
    if isinstance(node, ChecklistGroup):
        return [node.title, [_checklist_node_to_shorthand(child) for child in node.children]]
    if isinstance(node, str):
        return node
    return node


def _quiz_question_to_shorthand(question: QuizQuestion) -> dict[str, Any]:
    return _dump_model(question, by_alias=True)


def _widget_to_shorthand(widget: Widget) -> Any:
    if isinstance(widget, ParagraphWidget):
        return widget.text
    if isinstance(widget, CalloutWidget):
        return {widget.type: widget.text}
    if isinstance(widget, FlipWidget):
        items: list[Any] = [widget.front, widget.back]
        if widget.front_hint is not None or widget.back_hint is not None:
            items.append(widget.front_hint)
        if widget.back_hint is not None:
            items.append(widget.back_hint)
        return {"flip": _trim_trailing(items)}
    if isinstance(widget, TranslationWidget):
        return {"tr": [widget.source, widget.target]}
    if isinstance(widget, BlankWidget):
        return {"blank": [widget.prompt, widget.answer, widget.hint, widget.explanation]}
    if isinstance(widget, ListWidget):
        return {widget.type: list(widget.items)}
    if isinstance(widget, TableWidget):
        return {"table": list(widget.rows)}
    if isinstance(widget, CompareWidget):
        return {"compare": list(widget.rows)}
    if isinstance(widget, SwipeWidget):
        cards = [[card.text, card.correct_bucket, card.feedback] for card in widget.cards]
        return {"swipe": [widget.title, list(widget.buckets), cards]}
    if isinstance(widget, FreeTextWidget):
        values: list[Any] = [
            widget.prompt,
            widget.seed_locked,
            widget.text,
            widget.lang,
            widget.wordlist_csv,
            widget.mode,
        ]
        return {"freeText": _trim_trailing(values, default_map={2: "", 3: "en", 5: "multi"})}
    if isinstance(widget, StepFlowWidget):
        flow = [_step_flow_node_to_shorthand(node) for node in widget.flow]
        return {"stepFlow": [widget.lead, flow]}
    if isinstance(widget, AsciiDiagramWidget):
        return {"asciiDiagram": [widget.lead, widget.diagram]}
    if isinstance(widget, ChecklistWidget):
        tree = [_checklist_node_to_shorthand(node) for node in widget.tree]
        return {"checklist": [widget.lead, tree]}
    if isinstance(widget, ConsoleWidget):
        if widget.mode == 0:
            entries = [
                [entry.command, entry.delay_ms, entry.output] for entry in widget.rules_or_script
            ]
        else:
            entries = [
                [entry.pattern, entry.level, entry.output] for entry in widget.rules_or_script
            ]
        console_values = [widget.lead, widget.mode, entries]
        if widget.guided is not None:
            console_values.append([[step.task, step.solution] for step in widget.guided])
        return {"console": _trim_trailing(console_values)}
    if isinstance(widget, CodeViewerWidget):
        values = [widget.code, widget.language, widget.editable, widget.textarea_id]
        return {"codeviewer": _trim_trailing(values, default_map={2: False})}
    if isinstance(widget, TreeViewWidget):
        values = [widget.lesson, widget.title, widget.textarea_id, widget.editor_id]
        return {"treeview": _trim_trailing(values)}
    if isinstance(widget, QuizWidget):
        questions = [_quiz_question_to_shorthand(question) for question in widget.questions]
        return {"quiz": {"title": widget.title, "questions": questions}}
    return _dump_model(widget)


def _section_to_shorthand(section: SectionBlock) -> dict[str, Any]:
    data: dict[str, Any] = {
        "section": section.section,
        "items": [_widget_to_shorthand(widget) for widget in section.items],
    }
    if section.subsections:
        data["subsections"] = [_section_to_shorthand(sub) for sub in section.subsections]
    return data


def lesson_to_shorthand(lesson: LessonDocument) -> dict[str, Any]:
    """Serialize a validated lesson into the shorthand widget format."""

    data: dict[str, Any] = {
        "title": lesson.title,
        "blocks": [_section_to_shorthand(section) for section in lesson.blocks],
    }
    if lesson.version != "1.0":
        data["version"] = lesson.version
    return data
