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
WIDGET_PREFERENCES: dict[str, dict[str, list[str]]] = {}


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

    # Try exact match first
    blueprint_config = WIDGET_PREFERENCES.get(blueprint)
    
    # Fallback to case-insensitive match if needed (optional, but good for robustness)
    if not blueprint_config:
        for key, val in WIDGET_PREFERENCES.items():
            if key.lower() == blueprint.lower():
                blueprint_config = val
                break
    
    if not blueprint_config:
        return None

    if not teaching_style:
        return blueprint_config.get("all")

    styles = [teaching_style] if isinstance(teaching_style, str) else teaching_style
    
    # Use a set to merge widgets from multiple styles without duplicates
    merged_widgets: set[str] = set()
    found_any = False

    for style in styles:
        style_key = style.lower().strip()
        widgets = blueprint_config.get(style_key)
        
        if widgets:
            merged_widgets.update(widgets)
            found_any = True
    
    # If explicit styles yielded no widgets (e.g. unknown style), fallback to 'all'?
    # Or just return whatever we found. If we found nothing, maybe return None to default to all?
    # Let's say if we found nothing from explicit styles, we fallback to 'all'.
    if not found_any:
        return blueprint_config.get("all")

    return list(merged_widgets)
