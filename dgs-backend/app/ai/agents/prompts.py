"""Prompt helpers shared by agents."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ai.pipeline.contracts import GenerationRequest, PlanSection, SectionDraft
from app.schema.service import DEFAULT_WIDGETS_PATH, SchemaService
from app.schema.widgets_loader import load_widget_registry
from app.schema.widget_preference import get_widget_preference

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


@lru_cache(maxsize=1)
def _load_section_schema_text() -> str:
  """Load the section schema once to guide structurer and repair prompts."""
  schema_service = SchemaService()
  schema = schema_service.section_schema()
  return json.dumps(schema, indent=2, ensure_ascii=True)


def render_planner_prompt(request: Req) -> str:
  """Render the planner prompt for lesson planning with concrete substitutions."""
  prompt_template = _load_prompt(_resolve_planner_prompt_name(request.blueprint))
  primary_language = request.language or "English"
  
  if request.widgets:
    supported_widgets = ", ".join(request.widgets)
  else:
    supported_widgets = ", ".join(_supported_widgets())

  teaching_style = _teaching_style_addendum(request.teaching_style)
  details = request.prompt or "-"
  learner_level = request.learner_level or "Beginner"
  
  replacements = {
    "TOPIC": request.topic,
    "DETAILS": details,
    "LEARNER_LEVEL": learner_level,
    "DEPTH": request.depth,
    "SUPPORTED_WIDGETS": supported_widgets,
    "TEACHING_STYLE_ADDENDUM": teaching_style,
    "PRIMARY_LANGUAGE": primary_language,
    "SECTION_COUNT": str(request.section_count),
  }
  rendered_prompt = _replace_placeholders(prompt_template, replacements)
  return rendered_prompt


def render_gatherer_prompt(request: Req, section: PlanSection) -> str:
  """Render the gatherer prompt for a single section with explicit planner context."""
  prompt_template = _load_prompt("gatherer.md")
  plan_json = _serialize_plan_section(section)
  # Enforce that blueprint is provided to keep prompt selection consistent.
  
  if not request.blueprint:
    raise ValueError("Blueprint is required to render gatherer prompts.")
  
  tokens = {
    "PLANNER_SECTION_JSON": plan_json,
    "STYLE": _teaching_style_addendum(request.teaching_style),
    "BLUEPRINT": request.blueprint,
    "LEARNER_LEVEL": request.learner_level or "Beginner",
    "DEPTH": request.depth,
  }
  
  rendered_prompt = _replace_tokens(prompt_template, tokens)
  return rendered_prompt


def render_structurer_prompt(request: Req, section: Section, _schema_version: str) -> str:
  """Render the section structurer prompt with embedded gatherer and planner context."""
  prompt_template = _load_prompt("structurer.md")
  plan_json = _serialize_plan_section(section.plan_section)
  
  if request.widgets:
    allowed_widgets = request.widgets
  elif request.blueprint:
    allowed_widgets = get_widget_preference(request.blueprint, request.teaching_style)
  else:
    allowed_widgets = None

  if allowed_widgets:
    schema = SchemaService().subset_section_schema(allowed_widgets)
    widget_schema = json.dumps(schema, indent=2, ensure_ascii=True)
  else:
    widget_schema = _load_section_schema_text()
  
  replacements = {
    "GATHERER_CONTENT": section.raw_text or "Gatherer content missing.",
    "PLANNER_SECTION_JSON": plan_json,
    "WIDGET_SCHEMA_JSON": widget_schema,
    "STYLE": _teaching_style_addendum(request.teaching_style),
    "LEARNER_LEVEL": request.learner_level or "Unspecified",
  }
  
  rendered_template = _replace_tokens(prompt_template, replacements)
  return rendered_template


def render_gatherer_structurer_prompt(request: Req, section: PlanSection, _schema_version: str) -> str:
  """Render the merged gatherer+structurer prompt with planner and schema context."""
  prompt_template = _load_prompt("gatherer-structurer.md")
  plan_json = _serialize_plan_section(section)
  
  if request.widgets:
    allowed_widgets = request.widgets
  elif request.blueprint:
    allowed_widgets = get_widget_preference(request.blueprint, request.teaching_style)
  else:
    allowed_widgets = None

  if allowed_widgets:
    schema = SchemaService().subset_section_schema(allowed_widgets)
    widget_schema = json.dumps(schema, indent=2, ensure_ascii=True)
  else:
    widget_schema = _load_section_schema_text()
  
  # Enforce explicit blueprints so prompt content stays aligned with the plan.
  if not request.blueprint:
    raise ValueError("Blueprint is required to render gatherer-structurer prompts.")
  
  replacements = {
    "PLANNER_SECTION_JSON": plan_json,
    "WIDGET_SCHEMA_JSON": widget_schema,
    "STYLE": _teaching_style_addendum(request.teaching_style),
    "LEARNER_LEVEL": request.learner_level or "Unspecified",
    "DEPTH": request.depth,
    "BLUEPRINT": request.blueprint,
  }
  
  rendered_template = _replace_tokens(prompt_template, replacements)
  return rendered_template


def render_repair_prompt(
  _request: Req, _section: Section, repair_targets: list[dict[str, Any]],
  errors: Errors, widget_schemas: dict[str, Any],
) -> str:
  """Render the repair prompt for invalid JSON with embedded widget schema."""
  prompt_template = _load_prompt("repair.md")
  # Keep repair prompts focused on failing items and relevant widget shapes.
  rendered_template = _replace_tokens(prompt_template, {
    "WIDGETS_DOC": _load_widgets_text(),
    "WIDGET_SCHEMAS": json.dumps(widget_schemas, indent=2, ensure_ascii=True),
    "FAILED_ITEMS_JSON": json.dumps(repair_targets, indent=2, ensure_ascii=True),
    "ERRORS": "\n".join(f"- {error}" for error in errors),
  })
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


@lru_cache(maxsize=1)
def _load_widgets_text() -> str:
  try:
    path = Path(__file__).parents[2] / "schema" / "widgets_prompt.md"
    return path.read_text(encoding="utf-8").strip()
  except (FileNotFoundError, PermissionError, UnicodeDecodeError) as exc:
    raise RuntimeError(f"Failed to load widgets documentation: {exc}") from exc
