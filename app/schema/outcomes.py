"""Schemas for the Outcomes agent and API response contracts."""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

logger = logging.getLogger(__name__)

OUTCOME_TEXT_MIN_LENGTH = 3
OUTCOME_TEXT_MAX_LENGTH = 180
BLOCKED_REASON_BY_CATEGORY: dict[str, str] = {
  "sexual": "This topic is not allowed because sexual-content lessons are restricted on this platform.",
  "political": "This topic is not allowed because political advocacy lessons are restricted on this platform.",
  "military": "This topic is not allowed because military or warfare lessons are restricted on this platform.",
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
    - We carry the same request fields used by lesson generation so outcomes match the downstream pipeline context.
  """

  topic: StrictStr = Field(min_length=1, max_length=200, description="Lesson topic.")
  details: StrictStr | None = Field(default=None, min_length=1, max_length=300, description="Optional user-supplied details.")
  blueprint: StrictStr | None = Field(default=None, description="Optional blueprint or learning outcome guidance.")
  teaching_style: list[StrictStr] | None = Field(default=None, description="Optional teaching style guidance.")
  learner_level: StrictStr | None = Field(default=None, description="Optional learner level hint.")
  depth: StrictStr = Field(default="highlights", description="Requested depth hint (used only for prompt guidance).")
  lesson_language: StrictStr | None = Field(default="English", description="Primary language for the generated outcomes.")
  secondary_language: StrictStr | None = Field(default=None, description="Optional secondary language for language practice blueprint.")
  widgets: list[StrictStr] | None = Field(default=None, description="Optional widget ids to consider for the lesson.")
  max_outcomes: StrictInt = Field(default=5, ge=1, le=8, description="Maximum number of outcomes to return.")

  model_config = ConfigDict(extra="forbid")

  @model_validator(mode="after")
  def validate_secondary_language_scope(self) -> OutcomesAgentInput:
    """Enforce secondary language rules by blueprint context."""
    if str(self.blueprint or "") == "languagepractice" and self.secondary_language is None:
      raise ValueError("secondary_language is required when blueprint is languagepractice.")
    if self.secondary_language is not None and str(self.blueprint or "") != "languagepractice":
      raise ValueError("secondary_language is only allowed when blueprint is languagepractice.")
    return self


class OutcomesAgentResponse(BaseModel):
  """Structured response from the outcomes agent.

  How/Why:
    - We need a stable, machine-validated response that can be returned directly from an API endpoint.
    - The response intentionally supports a deny-path when a topic is disallowed.
  """

  ok: bool = Field(description="True when the topic is allowed and outcomes were generated.")
  error: Literal["TOPIC_NOT_ALLOWED"] | None = Field(default=None, description="Simple error code when the topic is blocked.")
  message: StrictStr | None = Field(default=None, min_length=1, max_length=240, description="Human-readable reason shown to end users when the topic is blocked.")
  blocked_category: Literal["sexual", "political", "military", "invalid_input"] | None = Field(default=None, description="High-level category used when blocking a topic.")
  outcomes: list[OutcomeText] = Field(default_factory=list, min_length=0, max_length=8, description="A small list of straightforward learning outcomes.")

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
      blocked_category = normalized.get("blocked_category")
      if isinstance(blocked_category, str):
        lowered = blocked_category.strip().lower()
        if lowered in {"sexual", "political", "military", "invalid_input"}:
          normalized["blocked_category"] = lowered
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
    return self


OUTCOMES_AGENT_RESPONSE_SCHEMA: dict = OutcomesAgentResponse.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")
