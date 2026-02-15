"""Widget preference configuration mapping blueprints and teaching approaches to allowed widgets."""

from __future__ import annotations

# Map blueprint -> teaching_approach -> list of widget types
# Teaching approaches: direct, socratic, narrative, experiential, adaptive
# - direct: Clear step-by-step guidance with structured explanations
# - socratic: Questions and discovery-based learning
# - narrative: Story-driven and contextual learning
# - experiential: Hands-on practice and real-world application
# - adaptive: Flexible mix of multiple approaches

CORE = ["markdown", "asciiDiagram", "mcqs"]

WIDGET_PREFERENCES: dict[str, dict[str, list[str]]] = {
  "Knowledge & Understanding": {
    "direct": CORE + ["table", "compare", "stepFlow"],
    "socratic": CORE + ["fillblank", "flipcards", "compare"],
    "narrative": CORE + ["table", "flipcards", "swipecards"],
    "experiential": CORE + ["fillblank", "swipecards", "freeText"],
    "adaptive": CORE + ["table", "compare", "flipcards", "fillblank", "swipecards"],
  },
  "Skill Building": {
    "direct": CORE + ["table", "stepFlow", "checklist"],
    "socratic": CORE + ["inputLine", "fillblank", "freeText"],
    "narrative": CORE + ["stepFlow", "flipcards"],
    "experiential": CORE + ["checklist", "inputLine", "freeText"],
    "adaptive": CORE + ["table", "stepFlow", "checklist", "inputLine", "freeText"],
  },
  "Critical Thinking": {
    "direct": CORE + ["compare", "table", "stepFlow"],
    "socratic": CORE + ["compare", "freeText", "fillblank", "swipecards"],
    "narrative": CORE + ["compare", "table", "flipcards"],
    "experiential": CORE + ["compare", "swipecards", "freeText", "stepFlow"],
    "adaptive": CORE + ["compare", "table", "flipcards", "swipecards", "freeText", "fillblank"],
  },
  "Planning and Productivity": {
    "direct": CORE + ["table", "stepFlow", "checklist"],
    "socratic": CORE + ["inputLine", "freeText", "compare"],
    "narrative": CORE + ["table", "flipcards", "compare"],
    "experiential": CORE + ["checklist", "stepFlow", "inputLine", "freeText"],
    "adaptive": CORE + ["table", "compare", "stepFlow", "checklist", "flipcards", "freeText"],
  },
  "Growth Mindset": {
    "direct": CORE + ["table", "compare", "flipcards"],
    "socratic": CORE + ["freeText", "inputLine", "compare"],
    "narrative": CORE + ["flipcards", "swipecards", "compare"],
    "experiential": CORE + ["freeText", "inputLine", "swipecards"],
    "adaptive": CORE + ["compare", "flipcards", "swipecards", "freeText", "inputLine"],
  },
  "Communication Skills": {
    "direct": CORE + ["table", "stepFlow", "compare"],
    "socratic": CORE + ["freeText", "inputLine", "compare"],
    "narrative": CORE + ["compare", "flipcards", "swipecards"],
    "experiential": CORE + ["freeText", "inputLine", "stepFlow", "swipecards"],
    "adaptive": CORE + ["compare", "table", "stepFlow", "flipcards", "freeText", "inputLine"],
  },
  "Movement and Fitness": {
    "direct": CORE + ["table", "stepFlow", "checklist"],
    "socratic": CORE + ["inputLine", "freeText", "compare"],
    "narrative": CORE + ["table", "flipcards"],
    "experiential": CORE + ["checklist", "stepFlow", "freeText", "inputLine"],
    "adaptive": CORE + ["table", "stepFlow", "checklist", "flipcards", "freeText"],
  },
  "Creative Skills": {
    "direct": CORE + ["table", "stepFlow"],
    "socratic": CORE + ["freeText", "inputLine", "fillblank"],
    "narrative": CORE + ["table", "flipcards", "compare"],
    "experiential": CORE + ["freeText", "inputLine", "checklist", "swipecards"],
    "adaptive": CORE + ["table", "compare", "flipcards", "fillblank", "freeText", "checklist"],
  },
  "Web Dev and Coding": {
    "direct": CORE + ["table", "codeEditor", "terminalDemo", "stepFlow"],
    "socratic": CORE + ["codeEditor", "inputLine", "freeText", "compare"],
    "narrative": CORE + ["table", "terminalDemo", "compare"],
    "experiential": CORE + ["codeEditor", "interactiveTerminal", "terminalDemo", "stepFlow", "checklist"],
    "adaptive": CORE + ["table", "compare", "codeEditor", "interactiveTerminal", "terminalDemo", "stepFlow", "checklist"],
  },
  "Language Practice": {
    "direct": CORE + ["tr", "table", "fillblank", "inputLine"],
    "socratic": CORE + ["tr", "fillblank", "inputLine", "freeText"],
    "narrative": CORE + ["tr", "flipcards", "compare", "table"],
    "experiential": CORE + ["tr", "fillblank", "inputLine", "freeText", "swipecards"],
    "adaptive": CORE + ["tr", "table", "compare", "flipcards", "fillblank", "inputLine", "freeText"],
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
