"""Prompt helpers shared by agents."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ai.pipeline.contracts import GenerationRequest, PlanSection, SectionDraft
from app.schema.service import DEFAULT_WIDGETS_PATH, SchemaService
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


def _replace_curly_placeholders(template: str, values: dict[str, str]) -> str:
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


def _teaching_style_addendum(style: str | None) -> str:
  """Explain how the chosen teaching style should shape structure and tone."""
  if not style:
    return "Blend conceptual clarity with practice; no teaching style preference was provided."

  normalized = style.strip().lower()
  mapping = {
    "conceptual": "Emphasize intuition and mental models before moving to practice.",
    "theoretical": "Prioritize formal correctness, proofs, and edge-case reasoning.",
    "practical": "Lead with application, drills, and feedback to reach outcomes quickly.",
    "all": "Sequence conceptual -> theoretical -> practical with increasing rigor and practice.",
  }
  if normalized in mapping:
    return mapping[normalized]

  return f"Honor the user's stated teaching style: {style}."


def _serialize_plan_section(plan_section: PlanSection | None) -> str:
  """Serialize planner output so gatherer and structurer can reference the intent."""
  if plan_section is None:
    return "Planner context unavailable for this section."

  return json.dumps(plan_section.model_dump(mode="json"), indent=2, ensure_ascii=True)


@lru_cache(maxsize=1)
def _load_section_schema_text() -> str:
  """Load the section schema once to guide structurer and repair prompts."""
  schema_service = SchemaService()
  schema = schema_service.section_schema()
  return json.dumps(schema, indent=2, ensure_ascii=True)


def render_gatherer_section_prompt(request: Req, section: PlanSection) -> str:
  """Render the gatherer prompt for a single section with explicit planner context."""
  prompt_template = _load_prompt("gatherer.md")
  plan_json = _serialize_plan_section(section)
  tokens = {
    "[PLANNER_SECTION_JSON]": plan_json,
    "STYLE": request.teaching_style or "Default to learner needs.",
    "BLUEPRINT": request.blueprint or "General",
    "LEARNER_LEVEL": request.learner_level or "Unspecified",
    "DEPTH": str(request.depth),
  }
  rendered_prompt = _replace_tokens(prompt_template, tokens)

  parts = [rendered_prompt, f"Topic: {request.topic}"]

  if request.prompt:
    parts.append(f"User Prompt: {request.prompt}")

  if request.language:
    parts.append(f"Language: {request.language}")

  parts.append(f"Constraints: {_stringify_constraints(request.constraints)}")
  parts.append(f"Section Number: {section.section_number}")
  parts.append(f"Section Title: {section.title}")

  if section.subsections:
    parts.append(f"Subsections: {', '.join(section.subsections)}")

  if section.planned_widgets:
    parts.append(f"Planned Widgets: {', '.join(section.planned_widgets)}")

  if section.goals:
    parts.append("Section Goals:")
    parts.extend(f"- {goal}" for goal in section.goals)

  if section.continuity_notes:
    parts.append("Continuity Notes:")
    parts.extend(f"- {note}" for note in section.continuity_notes)

  parts.append("Gather Prompt:")
  parts.append(section.gather_prompt)
  return "\n".join(parts)


def render_planner_prompt(request: Req) -> str:
  """Render the planner prompt for lesson planning with concrete substitutions."""
  prompt_template = _load_prompt(_planner_prompt_name(request.blueprint))
  primary_language = request.language or "English"
  supported_widgets = ", ".join(_supported_widgets())
  teaching_style = _teaching_style_addendum(request.teaching_style)
  details = request.prompt or "None provided."
  learner_level = request.learner_level or "unspecified"

  replacements = {
    "TOPIC": request.topic,
    "DETAILS": details,
    "LEARNER_LEVEL": learner_level,
    "DEPTH": str(request.depth),
    "SUPPORTED_WIDGETS": supported_widgets,
    "TEACHING_STYLE_ADDENDUM": teaching_style,
    "PRIMARY_LANGUAGE": primary_language,
    "SECTION_COUNT": str(request.depth),
  }
  rendered_prompt = _replace_curly_placeholders(prompt_template, replacements)

  parts = [
    rendered_prompt,
    "=== REQUEST CONTEXT ===",
    f"Topic: {request.topic}",
    f"Depth (sections): {request.depth}",
    f"Blueprint: {request.blueprint or 'default'}",
    f"Teaching Style: {request.teaching_style or ''}",
    f"Learner Level: {request.learner_level or ''}",
    f"Primary Language: {primary_language}",
  ]

  if request.prompt:
    parts.append(f"User Prompt: {request.prompt}")

  parts.append(f"Constraints: {_stringify_constraints(request.constraints)}")
  return "\n".join(parts)


def render_section_prompt(request: Req, section: Section, schema_version: str) -> str:
  """Render the section structurer prompt with embedded gatherer and planner context."""
  prompt_template = _load_prompt("structurer.md")
  plan_json = _serialize_plan_section(section.plan_section)
  widget_schema = _load_section_schema_text()
  replacements = {
    "GATHERER_CONTENT": section.raw_text or "Gatherer content missing.",
    "PLANNER_SECTION_JSON": plan_json,
    "WIDGET_SCHEMA_JSON": widget_schema,
  }
  rendered_template = _replace_tokens(prompt_template, replacements)
  teaching_style = request.teaching_style or "Default to learner needs."
  learner_level = request.learner_level or "Unspecified"
  rendered_template = rendered_template.replace("Teaching style: <…>", f"Teaching style: {teaching_style}")
  rendered_template = rendered_template.replace("Learner level: <…>", f"Learner level: {learner_level}")

  parts = [
    rendered_template,
    "=== BEGIN REQUEST CONTEXT ===",
    f"Topic: {request.topic}",
    f"User Prompt: {request.prompt or ''}",
    f"Language: {request.language or ''}",
    f"Constraints: {_stringify_constraints(request.constraints)}",
    f"Schema Version: {schema_version}",
    "=== END REQUEST CONTEXT ===",
    "=== BEGIN WIDGET RULES ===",
    _load_widgets_text(),
    "=== END WIDGET RULES ===",
    "=== BEGIN AGENT INPUT (SECTION TITLE) ===",
    section.title,
    "=== END AGENT INPUT (SECTION TITLE) ===",
    "=== BEGIN AGENT INPUT (SECTION CONTENT) ===",
    section.raw_text,
    "=== END AGENT INPUT (SECTION CONTENT) ===",
  ]
  return "\n".join(parts)


def render_repair_prompt(request: Req, section: Section, invalid_json: JsonDict, errors: Errors) -> str:
  """Render the repair prompt for invalid JSON with embedded widget schema."""
  prompt_template = _load_prompt("repair.md")
  rendered_template = _replace_tokens(prompt_template, {"WIDGETS_SCHEMA": _load_widgets_text()})

  parts = [
    rendered_template,
    f"Topic: {request.topic}",
    f"User Prompt: {request.prompt or ''}",
    f"Section Title: {section.title}",
    "Section Content:",
    section.raw_text,
    f"Constraints: {_stringify_constraints(request.constraints)}",
    "\nInvalid JSON:",
    json.dumps(invalid_json, indent=2),
    "\nValidation Errors:",
    "\n".join(f"- {error}" for error in errors),
    "\nProvide the corrected JSON:",
  ]
  return "\n".join(parts)


def format_schema_block(schema: dict[str, Any], *, label: str) -> str:
  """Format a JSON schema block for plain-text prompts."""
  schema_json = json.dumps(schema, indent=2, ensure_ascii=True)
  parts = [f"=== BEGIN {label} ===", schema_json, f"=== END {label} ==="]
  return "\n".join(parts)


def _planner_prompt_name(blueprint: str | None) -> str:
  """Resolve the planner prompt filename based on the blueprint selection."""
  if not blueprint:
    return "planner_default.md"
  # Normalize the blueprint label to an alphanumeric key so UI labels map to prompt files.
  normalized = "".join(ch for ch in blueprint.lower() if ch.isalnum())
  prompt_map = {
    "procedural": "planner_procedural.md",
    "factual": "planner_factual.md",
    "theory": "planner_factual.md",
    "social": "planner_social.md",
    "management": "planner_management.md",
    "planningmanagement": "planner_management.md",
    "ops": "planner_management.md",
    "somatic": "planner_somatic.md",
    "values": "planner_values.md",
    "metacognitive": "planner_metacognitive.md",
    "metacog": "planner_metacognitive.md",
    "critique": "planner_critique.md",
    "creativity": "planner_creativity.md",
    "create": "planner_creativity.md",
    "strategy": "planner_strategy.md",
  }
  return prompt_map.get(normalized, "planner_default.md")


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
