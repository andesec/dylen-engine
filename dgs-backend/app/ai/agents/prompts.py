"""Prompt helpers shared by agents."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ai.pipeline.contracts import GenerationRequest, PlanSection, SectionDraft

JsonDict = dict[str, Any]
Errors = list[str]
Req = GenerationRequest
Section = SectionDraft


def render_gatherer_section_prompt(request: Req, section: PlanSection) -> str:
  """Render the gatherer prompt for a single section."""
  prompt_template = _load_prompt("gatherer.md")
  parts = [prompt_template, f"Topic: {request.topic}"]
  if request.prompt:
    parts.append(f"User Prompt: {request.prompt}")
  if request.language:
    parts.append(f"Language: {request.language}")
  parts.append(f"Constraints: {request.constraints or {} }")
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
  """Render the planner prompt for lesson planning."""
  prompt_template = _load_prompt(_planner_prompt_name(request.blueprint))
  primary_language = request.language or ""
  # Provide explicit context so the planner can align sections to the selected blueprint and learner settings.
  parts = [
    prompt_template,
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
  parts.append(f"Constraints: {request.constraints or {} }")
  return "\n".join(parts)


def render_section_prompt(request: Req, section: Section, schema_version: str) -> str:
  """Render the section structurer prompt."""
  prompt_template = _load_prompt("structurer.md")
  parts = [
    prompt_template,
    "=== BEGIN REQUEST CONTEXT ===",
    f"Topic: {request.topic}",
    f"User Prompt: {request.prompt or ''}",
    f"Language: {request.language or ''}",
    f"Constraints: {request.constraints or {} }",
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
  """Render the repair prompt for invalid JSON."""
  prompt_template = _load_prompt("repair.md")
  parts = [
    prompt_template,
    f"Topic: {request.topic}",
    f"User Prompt: {request.prompt or ''}",
    f"Section Title: {section.title}",
    "Section Content:",
    section.raw_text,
    f"Constraints: {request.constraints or {} }",
    "Widgets:",
    _load_widgets_text(),
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
    "theory": "planner_theory.md",
    "social": "planner_social.md",
    "ops": "planner_ops.md",
    "somatic": "planner_somatic.md",
    "values": "planner_values.md",
    "metacog": "planner_metacog.md",
    "critique": "planner_critique.md",
    "create": "planner_create.md",
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
