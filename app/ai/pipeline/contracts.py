"""Shared data contracts for the AI pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schema.outcomes import OutcomeText


class GenerationRequest(BaseModel):
  """Inputs for a lesson generation request."""

  topic: str
  prompt: str | None = None
  outcomes: list[OutcomeText] | None = Field(default=None, min_length=1, max_length=8)
  depth: str
  section_count: int = Field(ge=1, le=10)
  blueprint: str | None = None
  teaching_style: list[str] | None = None
  language: str | None = None
  learner_level: str | None = None
  widgets: list[str] | None = Field(default=None, min_length=3, max_length=8)
  constraints: dict[str, Any] | None = None


class JobContext(BaseModel):
  """Context metadata for a generation job."""

  job_id: str
  created_at: datetime
  provider: str
  model: str
  request: GenerationRequest
  metadata: dict[str, Any] | None = None


class PlanSubsection(BaseModel):
  """Plan metadata for an individual lesson subsection."""

  title: str
  planned_widgets: list[str] = Field(default_factory=list)


class PlanSection(BaseModel):
  """Plan metadata for an individual lesson section."""

  section_number: int = Field(ge=1, le=10)
  title: str
  subsections: list[PlanSubsection]
  data_collection_points: list[str] = Field(default_factory=list)
  goals: str
  continuity_note: str


class LessonPlan(BaseModel):
  """Structured plan for a lesson."""

  sections: list[PlanSection]


class SectionDraft(BaseModel):
  """Raw content captured for a section along with the originating planner context to guide structuring."""

  section_number: int = Field(ge=1)
  title: str
  plan_section: PlanSection | None = None
  raw_text: str
  extracted_parts: dict[str, Any] | None = None


class StructuredSection(BaseModel):
  """Structured section output with validation metadata."""

  section_number: int = Field(ge=1)
  payload: dict[str, Any] = Field(serialization_alias="json", validation_alias="json", description="Validated section payload")
  validation_errors: list[str] = Field(default_factory=list)
  model_config = ConfigDict(populate_by_name=True)


class GatherBatchRequest(BaseModel):
  """Request parameters for a gatherer batch call."""

  section_start: int = Field(ge=1)
  section_end: int = Field(ge=1)
  depth: int = Field(ge=2, le=10)
  batch_index: int = Field(ge=1)
  batch_total: int = Field(ge=1)


class RepairInput(BaseModel):
  """Inputs for repairing a structured section."""

  section: SectionDraft
  structured: StructuredSection


class StructuredSectionBatch(BaseModel):
  """Batch container for structured sections."""

  sections: list[StructuredSection]


class RepairResult(BaseModel):
  """Repair output for a malformed section."""

  section_number: int = Field(ge=1)
  fixed_json: dict[str, Any]
  changes: list[str] = Field(default_factory=list)
  errors: list[str] = Field(default_factory=list)


class FinalLesson(BaseModel):
  """Final stitched lesson JSON with metadata."""

  lesson_json: dict[str, Any]
  metadata: dict[str, Any] | None = None
