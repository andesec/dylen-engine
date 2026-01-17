"""Widget preference configuration mapping blueprints and styles to allowed widgets."""

from __future__ import annotations

# Map blueprint -> style -> list of widget types
# The user will populate this structure.
# Example structure:
# {
#     "Creative Skills": {
#         "conceptual": ["p", "ul", "table"],
#         "theoretical": ["p", "table", "compare", "flip"],
#         "practical": ["freeText", "inputLine", "checklist", "mcqs"],
#         "all": ["p", "ul", "table", "compare", "flip", "freeText", "inputLine", "checklist", "mcqs"],
#     }
# }

CORE = ["p", "asciiDiagram", "mcqs"]
CORE_UL = ["ul"] + CORE
CORE_UL_WARN = ["ul", "warn"] + CORE

WIDGET_PREFERENCES: dict[str, dict[str, list[str]]] = {
    "Knowledge & Understanding": {
        "conceptual": CORE_UL + ["table", "compare", "flip"],
        "theoretical": CORE + ["table", "compare", "flip", "fillblank"],
        "practical": CORE + ["fillblank", "flip", "swipecards"],
    },
    "Skill Building": {
        "conceptual": CORE_UL + ["ol", "table"],
        "theoretical": CORE + ["ol", "table", "compare"],
        "practical": CORE_UL_WARN + ["ol", "stepFlow", "checklist", "inputLine"],
    },
    "Critical Thinking": {
        "conceptual": CORE + ["compare", "table"],
        "theoretical": CORE + ["compare", "table", "flip", "stepFlow"],
        "practical": CORE + ["compare", "table", "swipecards", "stepFlow", "freeText", "fillblank"],
    },
    "Planning and Productivity": {
        "conceptual": CORE_UL_WARN + ["table", "compare"],
        "theoretical": CORE_UL_WARN + ["table", "compare", "flip"],
        "practical": CORE_UL_WARN + ["ol", "stepFlow", "checklist", "table", "inputLine", "freeText"],
    },
    "Growth Mindset": {
        "conceptual": CORE_UL + ["compare"],
        "theoretical": CORE_UL + ["compare", "table", "flip"],
        "practical": CORE + ["flip", "freeText", "inputLine", "swipecards"],
    },
    "Communication Skills": {
        "conceptual": CORE_UL + ["compare"],
        "theoretical": CORE_UL + ["compare", "table", "flip"],
        "practical": CORE + ["compare", "swipecards", "freeText", "inputLine", "stepFlow"],
    },
    "Movement and Fitness": {
        "conceptual": CORE_UL + ["table"],
        "theoretical": CORE_UL + ["warn", "table", "compare"],
        "practical": CORE_UL_WARN + ["checklist", "stepFlow", "freeText", "inputLine"],
    },
    "Creative Skills": {
        "conceptual": CORE_UL + ["table"],
        "theoretical": CORE + ["table", "compare", "flip", "fillblank"],
        "practical": CORE + ["freeText", "inputLine", "checklist", "swipecards"],
    },
    "Web Dev and Coding": {
        "conceptual": CORE_UL_WARN + ["table", "compare", "checklist", "terminalDemo",  "codeEditor"],
        "theoretical": CORE_UL_WARN + ["table", "compare", "asciiDiagram", "terminalDemo",  "codeEditor"],
        "practical": CORE_UL_WARN + ["ol", "stepFlow", "checklist", "codeEditor", "interactiveTerminal", "terminalDemo", "swipecards", "err", "success"],
    },
    "Language Practice": {
        "conceptual": CORE_UL + ["tr", "flip", "fillblank", "inputLine"],
        "theoretical": CORE_UL + ["tr", "table", "compare", "fillblank", "flip"],
        "practical": CORE_UL_WARN + ["tr", "compare", "fillblank", "swipecards", "inputLine", "freeText", "ol"],
    },
}


def get_widget_preference(blueprint: str, teaching_style: str | list[str] | None) -> list[str] | None:
    """
    Return the list of allowed widgets for a given blueprint and teaching style.

    Args:
        blueprint: The lesson blueprint name (e.g., "Creative Skills").
        teaching_style: The teaching style(s) (e.g., "conceptual" or ["conceptual", "practical"]).

    Returns:
        list[str]: The specific list of allowed widgets if a preference matches.
        None: If no preference is defined (caller should default to all widgets).
    """
    if not blueprint:
        return None

    # Normalize blueprint keys to support id-style values.
    normalized = "".join(ch for ch in blueprint.lower() if ch.isalnum())
    blueprint_config = None

    # Resolve by normalized id or case-insensitive label match.
    for key, val in WIDGET_PREFERENCES.items():
        key_normalized = "".join(ch for ch in key.lower() if ch.isalnum())

        if key_normalized == normalized or key.lower() == blueprint.lower():
            blueprint_config = val
            break
    
    if not blueprint_config:
        return None

    if not teaching_style:
        styles = []
    else:
        styles = [teaching_style] if isinstance(teaching_style, str) else teaching_style
    
    # Use a set to merge widgets from multiple styles without duplicates
    merged_widgets: set[str] = set()
    found_any = False

    for style in styles:
        style_key = "".join(ch for ch in style.lower().strip() if ch.isalnum())
        widgets = blueprint_config.get(style_key)
        
        if widgets:
            merged_widgets.update(widgets)
            found_any = True
    
    # If explicit styles yielded no widgets (e.g. unknown style), fallback to 'all'?
    # Or just return whatever we found. If we found nothing, maybe return None to default to all?
    # Let's say if we found nothing from explicit styles, we fall back to 'all'.
    # Collect widgets from all styles if no specific style is requested or matched.
    if not found_any:
        # Fallback: compute the union of all styles defined for this blueprint.
        # This ensures we restrict to the blueprint's capabilities rather than allowing everything.
        all_widgets: set[str] = set()
        for style_widgets in blueprint_config.values():
            if isinstance(style_widgets, list):
                all_widgets.update(style_widgets)
        
        return list(all_widgets)

    return list(merged_widgets)
