"""Static lesson metadata for blueprints, teaching styles, and widget defaults."""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.schema.service import DEFAULT_WIDGETS_PATH
from app.schema.widgets_loader import load_widget_registry

_RAW_BLUEPRINTS: list[dict[str, Any]] = [
  {
    "id": "skillbuilding",
    "label": "Skill Building",
    "tooltip": "Build reliable step-by-step execution and repetition. Topics: Cooking fundamentals, workplace tools, study routines, home maintenance, keyboarding, lab technique, personal safety basics.",  # noqa: E501
  },
  {
    "id": "knowledgeunderstanding",
    "label": "Knowledge & Understanding",
    "tooltip": "Explain models, rules, and cause-and-effect clearly. Topics: Physics, biology, economics, history, linguistics, mathematics, political systems, music theory.",  # noqa: E501
  },
  {
    "id": "communicationskills",
    "label": "Communication Skills",
    "tooltip": "Practice guided interaction for better interpersonal outcomes. Topics: Negotiation, leadership, dating and relationships, teamwork, parenting, customer relations, conflict resolution, cross-cultural norms.",  # noqa: E501
  },
  {
    "id": "planningandproductivity",
    "label": "Planning and Productivity",
    "tooltip": "Design structure, sequencing, and sustainable systems. Topics: Project management, exam planning, personal finance systems, household systems, travel planning, event logistics, business operations.",  # noqa: E501
  },
  {
    "id": "movementandfitness",
    "label": "Movement and Fitness",
    "tooltip": "Build technique, form, and drill-based practice. Topics: Strength training, yoga, dance, swimming, voice training, instrument technique, handwriting, posture.",  # noqa: E501
  },
  {
    "id": "growthmindset",
    "label": "Growth Mindset",
    "tooltip": "Grow reflection, ethics, and worldview. Topics: Ethics, philosophy, civic responsibility, professional integrity, media ethics, sustainability, cultural humility.",  # noqa: E501
  },
  {
    "id": "criticalthinking",
    "label": "Critical Thinking",
    "tooltip": "Evaluate against standards and evidence. Topics: News credibility, research appraisal, art criticism, argument quality, product reviews, portfolio review, data interpretation.",  # noqa: E501
  },
  {"id": "creativeskills", "label": "Creative Skills", "tooltip": "Create original work under constraints. Topics: Creative writing, design, curriculum, music, visual art, storytelling, business concepts."},
  {"id": "webdevandcoding", "label": "Web Dev and Coding", "tooltip": "Hands-on implementation with tight feedback loops. Topics: Frontend fundamentals, engine basics, APIs, debugging, testing, refactoring, deployment."},
  {"id": "languagepractice", "label": "Language Practice", "tooltip": "Build fluency through guided practice. Topics: Vocabulary building, grammar fundamentals, conversation practice, listening practice, writing practice, pronunciation."},
]

_LEARNING_FOCUS: list[dict[str, Any]] = [
  {"id": "conceptual", "label": "Conceptual", "tooltip": "Mental models and intuition; understand how things work and why."},
  {"id": "applied", "label": "Applied", "tooltip": "Hands-on application; learn by doing and executing."},
  {"id": "comprehensive", "label": "Comprehensive", "tooltip": "Both theory and practice; complete understanding with application."},
]

_RAW_TEACHING_APPROACHES: list[dict[str, Any]] = [
  {"id": "direct", "label": "Direct Instruction", "tooltip": "Clear explanations with step-by-step guidance; efficient and structured."},
  {"id": "socratic", "label": "Socratic Questioning", "tooltip": "Questions that guide discovery; builds deep reasoning and insight."},
  {"id": "narrative", "label": "Narrative/Storytelling", "tooltip": "Stories and context that make concepts memorable and relatable."},
  {"id": "experiential", "label": "Experiential Practice", "tooltip": "Learning through doing, reflection, and iteration."},
  {"id": "adaptive", "label": "Adaptive Mix", "tooltip": "AI chooses the best approach for each section based on content."},
]

_LEARNER_LEVELS: list[dict[str, str]] = [
  {"id": "curious", "label": "Curious Explorer", "tooltip": "Just starting, no prior experience; gentle introduction to fundamentals."},
  {"id": "student", "label": "Active Student", "tooltip": "Learning actively with some familiarity; ready for guided practice."},
  {"id": "practitioner", "label": "Practitioner", "tooltip": "Applying knowledge regularly; ready for deeper analysis and nuance."},
  {"id": "specialist", "label": "Specialist", "tooltip": "Advanced expertise; focus on optimization, edge cases, and mastery."},
]

_SECTION_COUNT_OPTIONS: list[dict[str, Any]] = [
  {"id": "1", "label": "Quick Overview", "tooltip": "Brief introduction to the topic with essential concepts."},
  {"id": "2", "label": "Highlights", "tooltip": "Key concepts and takeaways for quick learning."},
  {"id": "3", "label": "Standard", "tooltip": "Balanced coverage with core concepts and practice."},
  {"id": "4", "label": "Detailed", "tooltip": "Comprehensive exploration with deeper analysis."},
  {"id": "5", "label": "In-Depth", "tooltip": "Thorough, extensive coverage with advanced topics."},
]

# Agent model ordering used by router fallbacks (not exposed in catalog responses).
_GATHERER_MODELS = ["gemini-2.5-flash", "vertex-gemini-2.5-flash"]

_STRUCTURER_MODELS = ["gemini-2.5-flash", "vertex-gemini-2.5-flash"]

_PLANNER_MODELS = ["gemini-2.5-flash", "vertex-gemini-2.5-flash"]

_REPAIRER_MODELS = ["gemini-2.0-flash", "vertex-gemini-2.0-flash"]

_OUTCOMES_MODELS = ["gemini-2.5-flash"]


def _merge_widgets(groups: list[list[str]]) -> list[str]:
  """Merge widget lists while preserving first-seen ordering."""
  merged: list[str] = []
  seen: set[str] = set()

  # Merge widgets while keeping the original order stable.
  for widgets in groups:
    # Iterate each widget in the group to preserve ordering.
    for widget in widgets:
      # Skip duplicates to keep the payload concise.
      if widget in seen:
        continue

      seen.add(widget)
      merged.append(widget)

  return merged


def _first_sentence(text: str) -> str:
  """Return a compact tooltip from a longer description."""
  cleaned = " ".join(text.split())

  # Prefer a short first sentence when possible.
  for delimiter in (". ", ".\n"):
    # Return early when we find a sentence boundary.
    if delimiter in cleaned:
      return cleaned.split(delimiter)[0].rstrip(".") + "."

  # Fall back to the cleaned string if no delimiter is found.
  return cleaned.strip()


def _build_widget_tooltip(description: str, label: str) -> str:
  """Build a concise widget tooltip describing purpose and behavior."""
  widget_key = label.strip()
  normalized = "".join(ch for ch in widget_key.lower() if ch.isalnum())
  tooltip_map = {
    "markdown": "Explain and format content with Markdown (text, callouts, lists).",
    "table": "Lay out facts so patterns and comparisons pop.",
    "compare": "Contrast two sides so the difference is obvious.",
    "asciidiagram": "Sketch a concept with simple text characters.",
    "flipcards": "Create flashcards that reward recall and surprise.",
    "mcqs": "Challenge understanding with crisp multiple choice options.",
    "freetext": "Invite the learner to think and answer in their own words.",
    "inputline": "Collect short, focused answers without friction.",
    "fillblank": "Reinforce memory by completing missing pieces.",
    "swipecards": "Sort ideas into buckets to reveal structure.",
    "stepflow": "Guide a journey with branching and guided steps.",
    "checklist": "Track progress with a satisfying, nested checklist.",
    "tr": "Practice translation pairs with quick recall loops.",
    "codeeditor": "View and write highlighted and formatted code for understanding and practical.",
    "interactiveterminal": "Practice commands like a real terminal session.",
    "terminaldemo": "Shows a command sequence as a guided demo.",
    "treeview": "Map hierarchies and breakdowns at a glance.",
    "fenster": "A custom made, topic-related interactive widget to demonstrate the concept.",
  }

  if normalized in tooltip_map:
    return tooltip_map[normalized]

  sentence = _first_sentence(description)

  # Prefix with a purpose cue when the description is too terse.
  if not sentence.lower().startswith(("use ", "used ", "for ", "helps ")):
    return f"Use for {label} content."

  return sentence


def _build_blueprint_options() -> list[dict[str, str]]:
  """Build blueprint option payloads with tooltip guidance."""
  options: list[dict[str, str]] = []

  # Merge blueprint metadata into a concise tooltip for UI display.
  for blueprint in _RAW_BLUEPRINTS:
    # Use the precomposed tooltip to keep the payload stable.
    tooltip = blueprint["tooltip"]
    options.append({"id": blueprint["id"], "label": blueprint["label"], "tooltip": tooltip})

  return options


def _build_learning_focus_options() -> list[dict[str, str]]:
  """Build learning focus option payloads with tooltip guidance."""
  options: list[dict[str, str]] = []

  # Use the composed tooltip for each focus to keep payload stable.
  for focus in _LEARNING_FOCUS:
    tooltip = focus["tooltip"]
    options.append({"id": focus["id"], "label": focus["label"], "tooltip": tooltip})

  return options


def _build_teaching_approach_options() -> list[dict[str, str]]:
  """Build teaching approach option payloads with tooltip guidance."""
  options: list[dict[str, str]] = []

  # Use the composed tooltip for each approach to keep payload stable.
  for approach in _RAW_TEACHING_APPROACHES:
    tooltip = approach["tooltip"]
    options.append({"id": approach["id"], "label": approach["label"], "tooltip": tooltip})

  return options


def _build_widget_options() -> list[dict[str, str]]:
  """Build widget option payloads with tooltip guidance."""
  options: list[dict[str, str]] = []
  seen_widget_ids: set[str] = set()
  registry = load_widget_registry(DEFAULT_WIDGETS_PATH)
  label_map = {
    "markdown": "Markdown Text",
    "table": "Table",
    "compare": "Comparison Table",
    "asciidiagram": "ASCII Diagram",
    "flipcards": "Flipcards",
    "mcqs": "Multiple Choice Question",
    "freetext": "Response Textbox",
    "inputline": "One liner Textbox",
    "fillblank": "Fill in the Blank",
    "swipecards": "Swipe Widget",
    "stepflow": "Step by Step Flow",
    "checklist": "Checklist",
    "tr": "Translation Panel",
    "codeeditor": "Code Editor",
    "interactiveterminal": "Interactive Terminal",
    "terminaldemo": "Demo Terminal",
    "treeview": "Tree View",
    "fenster": "Fenster Widget",
  }

  # Convert widget docs into concise tooltip strings.
  for widget_name in registry.available_types():
    # Normalize widget ids for client-friendly option keys.
    widget_id = "".join(ch for ch in widget_name.lower() if ch.isalnum())
    # Hide markdown from client-selectable widgets because the backend injects it automatically.
    if widget_id == "markdown":
      continue
    # Map the normalized id to a friendly label when available.
    widget_label = label_map.get(widget_id, widget_name)
    # Extract a brief tooltip for each widget entry.
    description = registry.describe(widget_name)
    tooltip = _build_widget_tooltip(description, widget_name)
    options.append({"id": widget_id, "label": widget_label, "tooltip": tooltip})
    seen_widget_ids.add(widget_id)

  # Add fenster explicitly so catalog stays aligned with backend-supported selective schemas.
  if "fenster" not in seen_widget_ids:
    options.append({"id": "fenster", "label": label_map["fenster"], "tooltip": _build_widget_tooltip("Interactive Fenster widget container.", "fenster")})

  return options


def build_lesson_catalog(settings: Settings) -> dict[str, Any]:
  """Return a static payload for lesson option metadata."""
  # Retain settings arg for compatibility with existing call sites.
  _ = settings

  # Assemble option payloads for selectable UI fields.
  blueprints = _build_blueprint_options()
  learning_focus = _build_learning_focus_options()
  teaching_approaches = _build_teaching_approach_options()
  widgets = _build_widget_options()
  return {"blueprints": blueprints, "learning_focus": learning_focus, "teaching_approaches": teaching_approaches, "learner_levels": list(_LEARNER_LEVELS), "section_counts": list(_SECTION_COUNT_OPTIONS), "widgets": widgets}
