"""Static lesson metadata for blueprints, teaching styles, and widget defaults."""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.schema.service import DEFAULT_WIDGETS_PATH
from app.schema.widget_preference import WIDGET_PREFERENCES
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
  {"id": "webdevandcoding", "label": "Web Dev and Coding", "tooltip": "Hands-on implementation with tight feedback loops. Topics: Frontend fundamentals, backend basics, APIs, debugging, testing, refactoring, deployment."},
  {"id": "languagepractice", "label": "Language Practice", "tooltip": "Build fluency through guided practice. Topics: Vocabulary building, grammar fundamentals, conversation practice, listening practice, writing practice, pronunciation."},
]

_RAW_TEACHING_STYLES: list[dict[str, Any]] = [
  {
    "id": "conceptual",
    "label": "Conceptual",
    "tooltip": "Intuition and mental models before application; best for fast clarity and orientation. Topics: Psychology basics, history overviews, nutrition basics, systems overviews, intro philosophy, big-picture science.",  # noqa: E501
  },
  {
    "id": "theoretical",
    "label": "Theoretical",
    "tooltip": "Formal and precise understanding; best for correctness, rigor, and edge cases. Topics: Grammar systems, formal logic, statistics, constitutional law, microeconomics, chemistry fundamentals.",  # noqa: E501
  },
  {
    "id": "practical",
    "label": "Practical",
    "tooltip": "Execution and application; best for getting results quickly. Topics: Language practice, fitness practice, cooking practice, public speaking practice, study practice, tool proficiency.",  # noqa: E501
  },
]

_LEARNER_LEVELS: list[dict[str, str]] = [
  {"id": "newbie", "label": "Newbie", "tooltip": "No prior exposure; use gentle pacing and foundational terms."},
  {"id": "beginner", "label": "Beginner", "tooltip": "Some familiarity; reinforce basics with guided practice."},
  {"id": "intermediate", "label": "Intermediate", "tooltip": "Solid fundamentals; add nuance, tradeoffs, and real scenarios."},
  {"id": "expert", "label": "Expert", "tooltip": "Advanced mastery; focus on edge cases, optimization, and depth."},
]

_DEPTH_OPTIONS: list[dict[str, str]] = [
  {"id": "highlights", "label": "Highlights", "tooltip": "Two concise sections for quick orientation and key takeaways."},
  {"id": "detailed", "label": "Detailed", "tooltip": "Six sections with a closing quiz for solid coverage."},
  {"id": "training", "label": "Training", "tooltip": "Ten sections with per-section practice and a comprehensive final exam."},
]

_GATHERER_MODELS = ["gemini-2.5-pro", "xiaomi/mimo-v2-flash:free", "deepseek/deepseek-r1-0528:free", "meta-llama/llama-3.1-405b-instruct:free", "openai/gpt-oss-120b:free", "vertex-gemini-2.5-pro", "vertex-gemini-3.0-pro"]

_STRUCTURER_MODELS = ["gemini-2.5-pro", "openai/gpt-oss-20b:free", "meta-llama/llama-3.3-70b-instruct:free", "google/gemma-3-27b-it:free", "vertex-gemini-2.5-pro", "vertex-gemini-3.0-pro"]

_PLANNER_MODELS = ["gemini-2.5-pro", "gemini-pro-latest", "openai/gpt-oss-120b:free", "xiaomi/mimo-v2-flash:free", "meta-llama/llama-3.1-405b-instruct:free", "deepseek/deepseek-r1-0528:free", "vertex-gemini-2.5-pro", "vertex-gemini-3.0-pro"]

_REPAIRER_MODELS = ["openai/gpt-oss-20b:free", "google/gemma-3-27b-it:free", "deepseek/deepseek-r1-0528:free", "gemini-2.5-flash", "vertex-gemini-2.5-flash", "vertex-gemini-3.0-flash"]


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
    "p": "Tell a clear idea in a warm, human voice.",
    "ul": "Snapshot the essentials in a fast, skimmable list.",
    "ol": "Walk the learner through a precise sequence of steps.",
    "table": "Lay out facts so patterns and comparisons pop.",
    "compare": "Contrast two sides so the difference is obvious.",
    "asciidiagram": "Sketch a concept with simple text visuals.",
    "flip": "Create flashcards that reward recall and surprise.",
    "mcqs": "Challenge understanding with crisp multiple choice.",
    "freetext": "Invite the learner to think and answer in their own words.",
    "inputline": "Collect short, focused answers without friction.",
    "fillblank": "Reinforce memory by completing missing pieces.",
    "swipecards": "Sort ideas into buckets to reveal structure.",
    "stepflow": "Guide a journey with branching, guided steps.",
    "checklist": "Track progress with a satisfying, nested checklist.",
    "info": "Spotlight a key insight the learner should pause on.",
    "warn": "Flag pitfalls and risks before they bite.",
    "success": "Celebrate a win or confirm the right move.",
    "err": "Name a common mistake and steer back on track.",
    "tr": "Practice translation pairs with quick recall loops.",
    "codeeditor": "Work through code with room to test and tweak.",
    "interactiveterminal": "Practice commands like a real terminal session.",
    "terminaldemo": "Show a command sequence as a guided demo.",
    "treeview": "Map hierarchies and breakdowns at a glance.",
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


def _build_teaching_style_options() -> list[dict[str, str]]:
  """Build teaching style option payloads with tooltip guidance."""
  options: list[dict[str, str]] = []

  # Use the composed tooltip for each style to keep payload stable.
  for style in _RAW_TEACHING_STYLES:
    # Use the precomposed tooltip to keep the payload stable.
    tooltip = style["tooltip"]
    options.append({"id": style["id"], "label": style["label"], "tooltip": tooltip})

  return options


def _build_widget_options() -> list[dict[str, str]]:
  """Build widget option payloads with tooltip guidance."""
  options: list[dict[str, str]] = []
  registry = load_widget_registry(DEFAULT_WIDGETS_PATH)
  label_map = {
    "p": "Paragraph",
    "ul": "Bullet List",
    "ol": "Numbered List",
    "table": "Table",
    "compare": "Comparison Table",
    "asciidiagram": "ASCII Diagram",
    "flip": "Flipcard",
    "mcqs": "Multiple Choice Question",
    "freetext": "Response Textbox",
    "inputline": "One liner Textbox",
    "fillblank": "Fill in the Blank",
    "swipecards": "Swipe Widget",
    "stepflow": "Step by Step Flow",
    "checklist": "Checklist",
    "warn": "Warning",
    "success": "Success Callout",
    "err": "Error Callout",
    "tr": "Translation Panel",
    "codeeditor": "Code Editor",
    "interactiveterminal": "Interactive Terminal",
    "terminaldemo": "Demo Terminal",
    "treeview": "Tree View",
  }

  # Convert widget docs into concise tooltip strings.
  for widget_name in registry.available_types():
    # Normalize widget ids for client-friendly option keys.
    widget_id = "".join(ch for ch in widget_name.lower() if ch.isalnum())
    # Map the normalized id to a friendly label when available.
    widget_label = label_map.get(widget_id, widget_name)
    # Extract a brief tooltip for each widget entry.
    description = registry.describe(widget_name)
    tooltip = _build_widget_tooltip(description, widget_name)
    options.append({"id": widget_id, "label": widget_label, "tooltip": tooltip})

  return options


def build_widget_defaults() -> dict[str, dict[str, list[str]]]:
  """Build default widget lists for each blueprint and teaching style."""
  defaults: dict[str, dict[str, list[str]]] = {}

  # Build defaults per blueprint so callers can cache this output safely.
  for blueprint, styles in WIDGET_PREFERENCES.items():
    # Normalize blueprint ids to align with client-facing option keys.
    blueprint_id = "".join(ch for ch in blueprint.lower() if ch.isalnum())
    style_defaults: dict[str, list[str]] = {}

    # Map explicit styles using lowercase option ids.
    for style_key in ("conceptual", "theoretical", "practical"):
      widgets = styles.get(style_key, [])
      # Normalize widget ids so defaults align with option ids.
      style_defaults[style_key] = ["".join(ch for ch in widget.lower() if ch.isalnum()) for widget in widgets]

    defaults[blueprint_id] = style_defaults

  return defaults


def _build_agent_models(settings: Settings) -> list[dict[str, Any]]:
  """Build agent model options including defaults."""
  options: list[dict[str, Any]] = []

  # Build each agent entry with default model values.
  options.append({"agent": "gatherer", "default": settings.gatherer_model, "options": _GATHERER_MODELS})
  options.append({"agent": "planner", "default": settings.planner_model, "options": _PLANNER_MODELS})
  options.append({"agent": "structurer", "default": settings.structurer_model, "options": _STRUCTURER_MODELS})
  options.append({"agent": "repairer", "default": settings.repair_model, "options": _REPAIRER_MODELS})

  # Keep a blank line after the loop for readability.

  return options


def build_lesson_catalog(settings: Settings) -> dict[str, Any]:
  """Return a static payload for lesson option metadata."""
  # Build widget defaults so the UI can reflect blueprint/style defaults.
  widget_defaults = build_widget_defaults()

  # Assemble option payloads for selectable UI fields.
  blueprints = _build_blueprint_options()
  teaching_styles = _build_teaching_style_options()
  widgets = _build_widget_options()
  agent_models = _build_agent_models(settings)
  return {"blueprints": blueprints, "teaching_styles": teaching_styles, "learner_levels": list(_LEARNER_LEVELS), "depths": list(_DEPTH_OPTIONS), "widgets": widgets, "agent_models": agent_models, "default_widgets": widget_defaults}
