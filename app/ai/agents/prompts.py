"""Prompt helpers shared by agents."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ai.pipeline.contracts import GenerationRequest, PlanSection, SectionDraft
from app.schema.service import DEFAULT_WIDGETS_PATH
from app.schema.widget_models import SECTION_TITLE_MAX_CHARS, SECTION_TITLE_MIN_CHARS, SUBSECTION_TITLE_MAX_CHARS, SUBSECTION_TITLE_MIN_CHARS, SUBSECTIONS_PER_SECTION_MAX, SUBSECTIONS_PER_SECTION_MIN
from app.schema.widgets_loader import load_widget_registry

JsonDict = dict[str, Any]
Errors = list[str]
Req = GenerationRequest
Section = SectionDraft


def _stringify_constraints(constraints: dict[str, Any] | None) -> str:
  """Serialize constraints to keep prompts deterministic and explicit."""
  if not constraints:
    return "{}"

  return json.dumps(constraints, ensure_ascii=True, sort_keys=True)


def _format_style(style: str | list[str] | None) -> str | None:
  """Format the teaching style for display in prompts."""
  if not style:
    return None
  if isinstance(style, str):
    return style
  return ", ".join(style)


def _format_outcomes(outcomes: list[str] | None) -> str:
  """Format optional outcomes as a prompt-friendly list."""
  if not outcomes:
    return "-"
  return "\n".join(f"- {item}" for item in outcomes)


def _replace_placeholders(template: str, values: dict[str, str]) -> str:
  """Substitute {{PLACEHOLDER}} markers so planner prompts carry actual context."""
  rendered = template
  for key, value in values.items():
    rendered = rendered.replace(f"{{{{{key}}}}}", value)

  return rendered


def _replace_tokens(template: str, values: dict[str, str]) -> str:
  """Replace bare tokens used by gatherer/structurer prompt templates."""
  rendered = template
  for key, value in values.items():
    rendered = rendered.replace(key, value)

  return rendered


@lru_cache(maxsize=1)
def _supported_widgets() -> list[str]:
  """List supported widget identifiers from the registry to constrain planners."""
  registry = load_widget_registry(DEFAULT_WIDGETS_PATH)
  return registry.available_types()


def _build_prompt_widgets(widgets: list[str] | None) -> list[str]:
  """Build a deterministic prompt widget list and always include markdown."""
  ordered_widgets: list[str] = []
  seen_widgets: set[str] = set()

  # Preserve caller order while dropping duplicates.
  for widget in widgets or []:
    if widget in seen_widgets:
      continue
    seen_widgets.add(widget)
    ordered_widgets.append(widget)

  # Markdown is backend-required and should never depend on frontend input.
  if "markdown" not in seen_widgets:
    ordered_widgets.append("markdown")

  return ordered_widgets


def _teaching_style_addendum(style: str | list[str] | None) -> str:
  """Explain how the chosen teaching style should shape structure and tone."""
  if not style:
    return "Blend conceptual clarity with practice; no teaching style preference was provided."

  styles = [style] if isinstance(style, str) else style
  descriptions = []

  mapping = {
    "conceptual": "Emphasize understanding, intuition and mental models before moving to practice.",
    "theoretical": "Prioritize formal correctness, proofs, and edge-case reasoning.",
    "practical": "Lead with application, drills, scenarios, and feedback to reach outcomes quickly.",
  }

  for s in styles:
    normalized = s.strip().lower()
    if normalized in mapping:
      descriptions.append(mapping[normalized])
    else:
      descriptions.append(f"Honor the user's stated teaching style: {s}.")

  return " ".join(descriptions)


def _serialize_plan_section(plan_section: PlanSection | None) -> str:
  """Serialize planner output so gatherer and structurer can reference the intent."""
  if plan_section is None:
    return "Planner context unavailable for this section."

  return json.dumps(plan_section.model_dump(mode="json"), separators=(",", ":"), ensure_ascii=True)


def render_planner_prompt(request: Req) -> str:
  """Render the planner prompt for lesson planning with concrete substitutions."""
  prompt_template = _load_prompt(_resolve_planner_prompt_name(request.blueprint))
  primary_language = request.lesson_language or "English"

  if request.widgets:
    supported_widgets = ", ".join(_build_prompt_widgets(request.widgets))
  else:
    supported_widgets = ", ".join(_build_prompt_widgets(_supported_widgets()))

  teaching_style = _teaching_style_addendum(request.teaching_style)
  outcomes = _format_outcomes(request.outcomes)
  details = request.prompt or "-"
  learner_level = request.learner_level or "Beginner"

  replacements = {
    "TOPIC": request.topic,
    "DETAILS": details,
    "OUTCOMES": outcomes,
    "LEARNER_LEVEL": learner_level,
    "DEPTH": request.depth,
    "SUPPORTED_WIDGETS": supported_widgets,
    "TEACHING_STYLE_ADDENDUM": teaching_style,
    "PRIMARY_LANGUAGE": primary_language,
    "SECTION_COUNT": str(request.section_count),
    "SUBSECTIONS_PER_SECTION_RULE": f"{SUBSECTIONS_PER_SECTION_MIN}-{SUBSECTIONS_PER_SECTION_MAX} subsections per section",
    "TITLE_CONSTRAINTS_RULE": (f"Section titles must be {SECTION_TITLE_MIN_CHARS}-{SECTION_TITLE_MAX_CHARS} chars; subsection titles must be {SUBSECTION_TITLE_MIN_CHARS}-{SUBSECTION_TITLE_MAX_CHARS} chars."),
  }
  rendered_prompt = _replace_placeholders(prompt_template, replacements)
  return rendered_prompt


def render_section_builder_prompt(request: Req, section: PlanSection, _schema_version: str) -> str:
  """Render the section builder prompt with planner and schema context."""
  prompt_template = _load_prompt("section_builder.md")
  plan_json = _serialize_plan_section(section)

  # Enforce explicit blueprints so prompt content stays aligned with the plan.
  if not request.blueprint:
    raise ValueError("Blueprint is required to render section builder prompts.")

  replacements = {"PLANNER_SECTION_JSON": plan_json, "STYLE": _teaching_style_addendum(request.teaching_style), "LEARNER_LEVEL": request.learner_level or "Unspecified", "DEPTH": request.depth, "BLUEPRINT": request.blueprint}

  rendered_template = _replace_tokens(prompt_template, replacements)
  return rendered_template


def render_repair_prompt(_request: Req, _section: Section, repair_targets: list[dict[str, Any]], errors: Errors) -> str:
  """Render the repair prompt for invalid JSON."""
  prompt_template = _load_prompt("repair.md")
  # Keep repair prompts focused on failing items and relevant widget shapes.
  rendered_template = _replace_tokens(prompt_template, {"FAILED_ITEMS_JSON": json.dumps(repair_targets, indent=2, ensure_ascii=True), "ERRORS": "\n".join(f"- {error}" for error in errors)})
  return rendered_template


def format_schema_block(schema: dict[str, Any], *, label: str) -> str:
  """Format a JSON schema block for plain-text prompts."""
  schema_json = json.dumps(schema, indent=2, ensure_ascii=True)
  parts = [f"=== BEGIN {label} ===", schema_json, f"=== END {label} ==="]
  return "\n".join(parts)


def _resolve_planner_prompt_name(blueprint: str | None) -> str:
  """Resolve the planner prompt filename based on the blueprint selection."""

  # Reject missing blueprints so planners always map to an explicit prompt.
  if not blueprint:
    raise ValueError("Blueprint is required and must match a supported planner prompt.")

  # Normalize the blueprint label to an alphanumeric key so UI labels map to prompt files.
  normalized = "".join(ch for ch in blueprint.lower() if ch.isalnum())
  prompt_map = {
    "skillbuilding": "planner_skill_building.md",
    "knowledgeunderstanding": "planner_knowledge_understanding.md",
    "communicationskills": "planner_communication_skills.md",
    "planningandproductivity": "planner_planning_productivity.md",
    "movementandfitness": "planner_movement_fitness.md",
    "growthmindset": "planner_growth_mindset.md",
    "criticalthinking": "planner_critical_thinking.md",
    "creativeskills": "planner_creative_skills.md",
    "webdevandcoding": "planner_coding.md",
    "languagepractice": "planner_language.md",
  }

  # Return a prompt filename only when the blueprint is supported.

  if normalized in prompt_map:
    return prompt_map[normalized]

  raise ValueError(f"Blueprint '{blueprint}' does not match a supported planner prompt.")


@lru_cache(maxsize=32)
def _load_prompt(name: str) -> str:
  try:
    path = Path(__file__).parents[1] / "prompts" / name
    return path.read_text(encoding="utf-8").strip()
  except (FileNotFoundError, PermissionError, UnicodeDecodeError) as exc:
    raise RuntimeError(f"Failed to load prompt '{name}': {exc}") from exc
