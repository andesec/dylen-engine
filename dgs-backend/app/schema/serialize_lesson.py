"""Serialize lesson models into the shorthand widget format."""

from __future__ import annotations

from typing import Any, cast

from .lesson_models import (
    AsciiDiagramWidget,
    BlankWidget,
    WarnWidget,
    ErrorWidget,
    SuccessWidget,
    ChecklistWidget,
    CodeViewerWidget,
    CompareWidget,
    ConsoleWidget,
    FlipWidget,
    FreeTextWidget,
    LessonDocument,
    UnorderedListWidget,
    OrderedListWidget,
    ParagraphWidget,
    QuizWidget,
    SectionBlock,
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


def _widget_to_shorthand(widget: Widget) -> Any:
    # If it's a plain string, it's a paragraph shorthand
    if isinstance(widget, str):
        return widget

    # If it's a model, we can just dump it because the models ARE the shorthand now.
    # Exception: ParagraphWidget might be used explicitly, dump it to { "p": ... }
    # but usually we might want to convert to string if possible?
    # The user requirements didn't say we MUST convert {p: "..."} to "...", but it's cleaner.
    if isinstance(widget, ParagraphWidget):
        return widget.p  # Convert explicit p-widget to string shorthand if preferred, or keep as object
        # Actually, let's keep it as the model dump if the user provided it as such,
        # BUT the model has field 'p', so dump gives {'p': 'text'}.
        # If the input was string, Pydantic parsed it as string (if allowed).
        # Wait, Widget union has `StrictStr`.

    return _dump_model(widget, by_alias=True)


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
    return data
