"""Schemas for the Outcomes agent and API response contracts."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

logger = logging.getLogger(__name__)

OUTCOME_TEXT_MIN_LENGTH = 3
OUTCOME_TEXT_MAX_LENGTH = 180
BLOCKED_REASON_BY_CATEGORY: dict[str, str] = {
  "explicit_sexual": "This topic is not allowed because it contains explicit sexual content. Educational topics like human reproduction, sexual health, and comprehensive sex education are permitted.",
  "political_advocacy": "This topic is not allowed because partisan political advocacy is restricted on this platform. Non-partisan civic education is permitted.",
  "military_warfare": "This topic is not allowed because military warfare training is restricted on this platform. Historical military studies and military science are permitted.",
  "invalid_input": "This topic was blocked because the input appears invalid or unclear. Please rephrase and try again.",
}

OutcomeText = StrictStr


def _warn_len_out_of_range(*, field_name: str, value: Any, min_length: int | None = None, max_length: int | None = None) -> None:
  """Log a warning when a string/list length falls outside configured bounds."""
  if value is None:
    return
  length = len(value) if isinstance(value, (str, list)) else None
  if length is None:
    return
  if min_length is not None and length < min_length:
    logger.warning("Outcomes length warning for %s: got %s, expected >= %s", field_name, length, min_length)
  if max_length is not None and length > max_length:
    logger.warning("Outcomes length warning for %s: got %s, expected <= %s", field_name, length, max_length)


class OutcomesAgentInput(BaseModel):
  """Inputs for generating learning outcomes for a lesson topic.

  How/Why:
    - The outcomes agent runs before lesson generation to validate a topic and propose a small set of goals.
    - The agent will suggest an appropriate blueprint and teacher persona based on the topic.
  """

  topic: StrictStr = Field(min_length=1, max_length=200, description="Lesson topic.")
  details: StrictStr | None = Field(default=None, min_length=1, max_length=300, description="Optional user-supplied details.")
  teaching_style: list[StrictStr] | None = Field(default=None, description="Optional teaching style guidance.")
  learner_level: StrictStr | None = Field(default=None, description="Optional learner level hint.")
  depth: StrictStr = Field(default="highlights", description="Requested depth hint (used only for prompt guidance).")
  lesson_language: StrictStr | None = Field(default="English", description="Primary language for the generated outcomes.")
  secondary_language: StrictStr | None = Field(default=None, description="Optional secondary language for language practice lessons (only relevant for language topics).")
  max_outcomes: StrictInt = Field(default=5, ge=1, le=8, description="Maximum number of outcomes to return.")

  model_config = ConfigDict(extra="forbid")


class OutcomesAgentResponse(BaseModel):
  """Structured response from the outcomes agent.

  How/Why:
    - We need a stable, machine-validated response that can be returned directly from an API endpoint.
    - The response intentionally supports a deny-path when a topic is disallowed.
    - The agent now suggests the best-fit blueprint and teacher persona for the topic.
  """

  ok: bool = Field(description="True when the topic is allowed and outcomes were generated.")
  error: Literal["TOPIC_NOT_ALLOWED"] | None = Field(default=None, description="Simple error code when the topic is blocked.")
  message: StrictStr | None = Field(default=None, min_length=1, max_length=240, description="Human-readable reason shown to end users when the topic is blocked.")
  blocked_category: Literal["explicit_sexual", "political_advocacy", "military_warfare", "invalid_input"] | None = Field(default=None, description="High-level category used when blocking a topic.")
  outcomes: list[OutcomeText] = Field(default_factory=list, min_length=0, max_length=8, description="A small list of straightforward learning outcomes.")
  suggested_blueprint: StrictStr | None = Field(default=None, min_length=3, max_length=50, description="The recommended blueprint/framework for this topic (e.g., 'knowledge_understanding', 'languagepractice').")
  teacher_persona: StrictStr | None = Field(default=None, min_length=3, max_length=100, description="The ideal instructor archetype for this content (e.g., 'Socratic Professor', 'Workshop Facilitator').")

  model_config = ConfigDict(extra="forbid")

  @model_validator(mode="before")
  @classmethod
  def normalize_blocked_payload(cls, data: Any) -> Any:
    """Normalize blocked responses into a strict API-safe contract.

    How/Why:
      - Providers occasionally return descriptive safety text instead of a strict error enum.
      - Canonicalizing blocked payloads keeps endpoint behavior stable and avoids avoidable 500s.
    """
    # Only normalize object payloads because pydantic handles non-object input errors itself.
    if not isinstance(data, dict):
      return data
    normalized = dict(data)
    # Normalize the deny path to match the strict literal schema expected by downstream clients.
    if normalized.get("ok") is False:
      error = normalized.get("error")
      message = normalized.get("message")
      # Convert prior provider text errors into a user-facing message without losing strict error coding.
      if not isinstance(message, str) or message.strip() == "":
        if isinstance(error, str) and error.strip() != "" and error.strip() != "TOPIC_NOT_ALLOWED":
          normalized["message"] = error.strip()
      if isinstance(error, str) and error.strip() != "TOPIC_NOT_ALLOWED":
        normalized["error"] = "TOPIC_NOT_ALLOWED"
      # Normalize blocked category casing and fallback missing/unknown values to invalid_input.
      # Support both old and new category names for backward compatibility during migration.
      blocked_category = normalized.get("blocked_category")
      if isinstance(blocked_category, str):
        lowered = blocked_category.strip().lower()
        # Map old category names to new ones for consistency
        category_mapping = {"sexual": "explicit_sexual", "political": "political_advocacy", "military": "military_warfare"}
        normalized_category = category_mapping.get(lowered, lowered)
        if normalized_category in {"explicit_sexual", "political_advocacy", "military_warfare", "invalid_input"}:
          normalized["blocked_category"] = normalized_category
        else:
          normalized["blocked_category"] = "invalid_input"
      elif blocked_category is None:
        normalized["blocked_category"] = "invalid_input"
      # Ensure blocked responses always carry a clear end-user message.
      if not isinstance(normalized.get("message"), str) or str(normalized.get("message")).strip() == "":
        category = str(normalized.get("blocked_category") or "invalid_input")
        normalized["message"] = BLOCKED_REASON_BY_CATEGORY.get(category, BLOCKED_REASON_BY_CATEGORY["invalid_input"])
      # Drop any accidental outcomes to preserve blocked response semantics.
      outcomes = normalized.get("outcomes")
      if isinstance(outcomes, list) and outcomes:
        normalized["outcomes"] = []
    # Strip stray message text from success payloads to preserve consistent response shape.
    if normalized.get("ok") is True and normalized.get("message") is not None:
      normalized["message"] = None
    return normalized

  @model_validator(mode="after")
  def validate_outcome_shape(self) -> OutcomesAgentResponse:
    # Enforce consistent response shape so clients can rely on predictable semantics.
    if not self.ok:
      if not self.error:
        raise ValueError("error is required when ok is false.")
      if not self.message:
        raise ValueError("message is required when ok is false.")
      if self.outcomes:
        raise ValueError("outcomes must be empty when ok is false.")
      if self.blocked_category is None:
        raise ValueError("blocked_category is required when ok is false.")
      if self.suggested_blueprint is not None:
        raise ValueError("suggested_blueprint must be null when ok is false.")
      if self.teacher_persona is not None:
        raise ValueError("teacher_persona must be null when ok is false.")
    else:
      if self.error is not None:
        raise ValueError("error must be null when ok is true.")
      if self.message is not None:
        raise ValueError("message must be null when ok is true.")
      if self.blocked_category is not None:
        raise ValueError("blocked_category must be null when ok is true.")
      if not self.outcomes:
        raise ValueError("outcomes must be non-empty when ok is true.")
      if len(self.outcomes) > 8:
        raise ValueError("outcomes must be a small list (max 8).")
      for index, outcome in enumerate(self.outcomes):
        _warn_len_out_of_range(field_name=f"outcomes[{index}]", value=outcome, min_length=OUTCOME_TEXT_MIN_LENGTH, max_length=OUTCOME_TEXT_MAX_LENGTH)
      # Suggested blueprint and teacher persona should be present for successful outcomes
      if not self.suggested_blueprint:
        logger.warning("Outcomes agent did not return a suggested_blueprint")
      if not self.teacher_persona:
        logger.warning("Outcomes agent did not return a teacher_persona")
    return self


OUTCOMES_AGENT_RESPONSE_SCHEMA: dict = OutcomesAgentResponse.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")
