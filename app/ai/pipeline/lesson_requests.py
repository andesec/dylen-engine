"""Msgspec request models for lesson generation workflow."""

from __future__ import annotations

from typing import Literal

from app.ai.pipeline.contracts import PipelineStruct


class GenerateLessonRequestStruct(PipelineStruct):
  """Msgspec model used by worker and job handlers for lesson requests."""

  topic: str
  outcomes: list[str]
  blueprint: Literal["skillbuilding", "knowledgeunderstanding", "communicationskills", "planningandproductivity", "movementandfitness", "growthmindset", "criticalthinking", "creativeskills", "webdevandcoding", "languagepractice"]
  teaching_style: list[Literal["conceptual", "theoretical", "practical"]]
  details: str | None = None
  learner_level: str | None = None
  depth: Literal["highlights", "detailed", "training"] = "highlights"
  lesson_language: Literal["English", "German", "Urdu"] = "English"
  secondary_language: Literal["English", "German", "Urdu"] | None = None
  widgets: list[str] | None = None
  schema_version: str | None = None
  idempotency_key: str | None = None

  def __post_init__(self) -> None:
    if len(self.outcomes) < 1 or len(self.outcomes) > 8:
      raise ValueError("outcomes must include 1-8 values.")
    if self.blueprint == "languagepractice" and self.secondary_language is None:
      raise ValueError("secondary_language is required when blueprint is languagepractice.")
    if self.secondary_language is not None and self.blueprint != "languagepractice":
      raise ValueError("secondary_language is only allowed when blueprint is languagepractice.")
