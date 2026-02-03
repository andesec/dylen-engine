"""Schemas for the Outcomes agent and API response contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

OutcomeText = Annotated[StrictStr, Field(min_length=3, max_length=140)]


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
  primary_language: StrictStr | None = Field(default="English", description="Primary language for the generated outcomes.")
  widgets: list[StrictStr] | None = Field(default=None, description="Optional widget ids to consider for the lesson.")
  max_outcomes: StrictInt = Field(default=5, ge=1, le=8, description="Maximum number of outcomes to return.")

  model_config = ConfigDict(extra="forbid")


class OutcomesAgentResponse(BaseModel):
  """Structured response from the outcomes agent.

  How/Why:
    - We need a stable, machine-validated response that can be returned directly from an API endpoint.
    - The response intentionally supports a deny-path when a topic is disallowed.
  """

  ok: bool = Field(description="True when the topic is allowed and outcomes were generated.")
  error: Literal["TOPIC_NOT_ALLOWED"] | None = Field(default=None, description="Simple error code when the topic is blocked.")
  blocked_category: Literal["sexual", "political", "military"] | None = Field(default=None, description="High-level category used when blocking a topic.")
  outcomes: list[OutcomeText] = Field(default_factory=list, min_length=0, max_length=8, description="A small list of straightforward learning outcomes.")

  model_config = ConfigDict(extra="forbid")

  @model_validator(mode="after")
  def validate_outcome_shape(self) -> OutcomesAgentResponse:
    # Enforce consistent response shape so clients can rely on predictable semantics.
    if not self.ok:
      if not self.error:
        raise ValueError("error is required when ok is false.")
      if self.outcomes:
        raise ValueError("outcomes must be empty when ok is false.")
      if self.blocked_category is None:
        raise ValueError("blocked_category is required when ok is false.")
    else:
      if self.error is not None:
        raise ValueError("error must be null when ok is true.")
      if self.blocked_category is not None:
        raise ValueError("blocked_category must be null when ok is true.")
      if not self.outcomes:
        raise ValueError("outcomes must be non-empty when ok is true.")
      if len(self.outcomes) > 8:
        raise ValueError("outcomes must be a small list (max 8).")
    return self


OUTCOMES_AGENT_RESPONSE_SCHEMA: dict = OutcomesAgentResponse.model_json_schema(by_alias=True, ref_template="#/$defs/{model}", mode="validation")
