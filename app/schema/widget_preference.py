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

CORE = ["markdown", "asciiDiagram", "mcqs"]

WIDGET_PREFERENCES: dict[str, dict[str, list[str]]] = {
  "Knowledge & Understanding": {"conceptual": CORE + ["table", "compare", "flip"], "theoretical": CORE + ["table", "compare", "flip", "fillblank"], "practical": CORE + ["fillblank", "flip", "swipecards"]},
  "Skill Building": {"conceptual": CORE + ["table"], "theoretical": CORE + ["table", "compare"], "practical": CORE + ["stepFlow", "checklist", "inputLine"]},
  "Critical Thinking": {"conceptual": CORE + ["compare", "table"], "theoretical": CORE + ["compare", "table", "flip", "stepFlow"], "practical": CORE + ["compare", "table", "swipecards", "stepFlow", "freeText", "fillblank"]},
  "Planning and Productivity": {"conceptual": CORE + ["table", "compare"], "theoretical": CORE + ["table", "compare", "flip"], "practical": CORE + ["stepFlow", "checklist", "table", "inputLine", "freeText"]},
  "Growth Mindset": {"conceptual": CORE + ["compare"], "theoretical": CORE + ["compare", "table", "flip"], "practical": CORE + ["flip", "freeText", "inputLine", "swipecards"]},
  "Communication Skills": {"conceptual": CORE + ["compare"], "theoretical": CORE + ["compare", "table", "flip"], "practical": CORE + ["compare", "swipecards", "freeText", "inputLine", "stepFlow"]},
  "Movement and Fitness": {"conceptual": CORE + ["table"], "theoretical": CORE + ["table", "compare"], "practical": CORE + ["checklist", "stepFlow", "freeText", "inputLine"]},
  "Creative Skills": {"conceptual": CORE + ["table"], "theoretical": CORE + ["table", "compare", "flip", "fillblank"], "practical": CORE + ["freeText", "inputLine", "checklist", "swipecards"]},
  "Web Dev and Coding": {
    "conceptual": CORE + ["table", "compare", "checklist", "terminalDemo", "codeEditor"],
    "theoretical": CORE + ["table", "compare", "asciiDiagram", "terminalDemo", "codeEditor"],
    "practical": CORE + ["stepFlow", "checklist", "codeEditor", "interactiveTerminal", "terminalDemo", "swipecards"],
  },
  "Language Practice": {"conceptual": CORE + ["tr", "flip", "fillblank", "inputLine"], "theoretical": CORE + ["tr", "table", "compare", "fillblank", "flip"], "practical": CORE + ["tr", "compare", "fillblank", "swipecards", "inputLine", "freeText"]},
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
