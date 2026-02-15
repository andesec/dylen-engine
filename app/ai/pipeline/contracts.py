"""Shared data contracts for the AI pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

import msgspec

TStruct = TypeVar("TStruct", bound="PipelineStruct")


class PipelineStruct(msgspec.Struct, kw_only=True):
  """Base msgspec struct with Pydantic-like helper methods."""

  @classmethod
  def model_validate(cls: type[TStruct], payload: Any) -> TStruct:
    return msgspec.convert(payload, type=cls)

  def model_dump(self, *, mode: str = "python", by_alias: bool = False) -> dict[str, Any]:
    _ = (mode, by_alias)
    return msgspec.to_builtins(self)  # type: ignore[return-value]


class GenerationRequest(PipelineStruct):
  """Inputs for a lesson generation request."""

  topic: str
  section_count: int
  prompt: str | None = None
  outcomes: list[str] | None = None
  blueprint: str | None = None
  learning_focus: str | None = None
  teaching_style: list[str] | None = None
  lesson_language: str | None = None
  secondary_language: str | None = None
  learner_level: str | None = None
  widgets: list[str] | None = None
  constraints: dict[str, Any] | None = None


class JobContext(PipelineStruct):
  """Context metadata for a generation job."""

  job_id: str
  created_at: datetime
  provider: str
  model: str
  request: GenerationRequest
  metadata: dict[str, Any] | None = None


class PlanSubsection(PipelineStruct):
  """Plan metadata for an individual lesson subsection."""

  title: str
  planned_widgets: list[str] = msgspec.field(default_factory=list)


class PlanSection(PipelineStruct):
  """Plan metadata for an individual lesson section."""

  section_number: int
  title: str
  subsections: list[PlanSubsection]
  goals: str
  continuity_note: str
  data_collection_points: list[str] = msgspec.field(default_factory=list)


class LessonPlan(PipelineStruct):
  """Structured plan for a lesson."""

  sections: list[PlanSection]


class SectionDraft(PipelineStruct):
  """Raw content captured for a section along with planner context."""

  section_number: int
  title: str
  raw_text: str
  plan_section: PlanSection | None = None
  extracted_parts: dict[str, Any] | None = None


class StructuredSection(PipelineStruct):
  """Structured section output with validation metadata."""

  section_number: int
  payload: dict[str, Any]
  validation_errors: list[str] = msgspec.field(default_factory=list)
  db_section_id: int | None = None


class GatherBatchRequest(PipelineStruct):
  """Request parameters for a gatherer batch call."""

  section_start: int
  section_end: int
  depth: int
  batch_index: int
  batch_total: int


class RepairInput(PipelineStruct):
  """Inputs for repairing a structured section."""

  section: SectionDraft
  structured: StructuredSection


class StructuredSectionBatch(PipelineStruct):
  """Batch container for structured sections."""

  sections: list[StructuredSection]


class RepairResult(PipelineStruct):
  """Repair output for a malformed section."""

  section_number: int
  fixed_json: dict[str, Any]
  changes: list[str] = msgspec.field(default_factory=list)
  errors: list[str] = msgspec.field(default_factory=list)
