from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from app.jobs.guardrails import MAX_ITEM_BYTES
from app.jobs.models import JobStatus
from app.schema.outcomes import OutcomeText
from app.services.widgets import _normalize_option_id, _normalize_widget_ids

MAX_REQUEST_BYTES = MAX_ITEM_BYTES // 2


class ValidationResponse(BaseModel):
  """Response model for lesson validation results."""

  ok: bool
  errors: list[str]


class SectionBuilderModel(str, Enum):
  """Model options for the section builder agent."""

  GEMINI_25_FLASH = "gemini-2.5-flash"
  GEMINI_25_PRO = "gemini-2.5-pro"
  XIAOMI_MIMO_V2_FLASH = "xiaomi/mimo-v2-flash:free"
  DEEPSEEK_R1_0528 = "deepseek/deepseek-r1-0528:free"
  LLAMA_31_405B = "meta-llama/llama-3.1-405b-instruct:free"
  GPT_OSS_120B = "openai/gpt-oss-120b:free"
  GEMMA_3_27B = "google/gemma-3-27b-it:free"
  GPT_OSS_20B = "openai/gpt-oss-20b:free"
  LLAMA_33_70B = "meta-llama/llama-3.3-70b-instruct:free"


class PlannerModel(str, Enum):
  """Model options for the planning agent."""

  GEMINI_25_PRO = "gemini-2.5-pro"
  GEMINI_PRO_LATEST = "gemini-pro-latest"
  GPT_OSS_120B = "openai/gpt-oss-120b:free"
  XIAOMI_MIMO_V2_FLASH = "xiaomi/mimo-v2-flash:free"
  LLAMA_31_405B = "meta-llama/llama-3.1-405b-instruct:free"
  DEEPSEEK_R1_0528 = "deepseek/deepseek-r1-0528:free"


class RepairerModel(str, Enum):
  """Model options for the repair agent."""

  GPT_OSS_20B = "openai/gpt-oss-20b:free"
  GEMMA_3_27B = "google/gemma-3-27b-it:free"
  DEEPSEEK_R1_0528 = "deepseek/deepseek-r1-0528:free"
  GEMINI_25_FLASH = "gemini-2.5-flash"


class BaseLessonRequest(BaseModel):
  """Shared request payload for lesson generation and outcomes preflight."""

  topic: StrictStr = Field(min_length=1, description="Topic to generate a lesson for.", examples=["Introduction to Python"])
  details: StrictStr | None = Field(default=None, min_length=1, max_length=300, description="Optional user-supplied details (max 300 characters).", examples=["Focus on lists and loops"])
  blueprint: Literal["skillbuilding", "knowledgeunderstanding", "communicationskills", "planningandproductivity", "movementandfitness", "growthmindset", "criticalthinking", "creativeskills", "webdevandcoding", "languagepractice"] = Field(
    description="Required blueprint guidance for lesson planning."
  )
  teaching_style: list[Literal["conceptual", "theoretical", "practical"]] = Field(min_length=1, max_length=3, description="Required teaching style guidance for lesson planning.")
  learner_level: StrictStr | None = Field(default=None, min_length=1, description="Optional learner level hint used for prompt guidance.")
  depth: Literal["highlights", "detailed", "training"] = Field(default="highlights", description="Requested lesson depth (Highlights=2, Detailed=6, Training=10).")
  lesson_language: Literal["English", "German", "Urdu"] = Field(default="English", description="Primary language for lesson output.")
  secondary_language: Literal["English", "German", "Urdu"] | None = Field(default=None, description="Optional secondary language for language practice blueprint.")
  widgets: list[StrictStr] | None = Field(default=None, min_length=3, max_length=7, description="Optional list of allowed widgets (overrides defaults).")
  schema_version: StrictStr | None = Field(default=None, description="Optional schema version to pin the lesson output to.")
  idempotency_key: StrictStr | None = Field(default=None, description="Optional client-generated UUID to prevent duplicate processing of the same request.")
  model_config = ConfigDict(extra="forbid")

  @model_validator(mode="before")
  @classmethod
  def normalize_option_ids(cls, values: Any) -> Any:
    # Normalize option ids so API inputs align with catalog ids.
    if not isinstance(values, dict):
      return values

    data = dict(values)
    blueprint = data.get("blueprint")

    if isinstance(blueprint, str):
      data["blueprint"] = _normalize_option_id(blueprint)

    teaching_style = data.get("teaching_style")

    if isinstance(teaching_style, list):
      normalized_styles: list[str] = []

      for style in teaching_style:
        # Enforce string-only entries for teaching styles.
        if not isinstance(style, str):
          raise ValueError("Teaching style entries must be strings.")
        normalized_styles.append(_normalize_option_id(style))

      data["teaching_style"] = normalized_styles

    learner_level = data.get("learner_level")

    if isinstance(learner_level, str):
      data["learner_level"] = _normalize_option_id(learner_level)

    secondary_language = data.get("secondary_language")
    if isinstance(secondary_language, str):
      # Normalize common client formats and empty strings before enum validation.
      language_value = secondary_language.strip()
      if language_value == "":
        data["secondary_language"] = None
      else:
        # Ignore secondary_language for non-language blueprints to keep the API backward-compatible.
        blueprint_value = data.get("blueprint")
        if blueprint_value != "languagepractice":
          data["secondary_language"] = None
        else:
          language_aliases = {"english": "English", "en": "English", "german": "German", "de": "German", "urdu": "Urdu", "ur": "Urdu"}
          data["secondary_language"] = language_aliases.get(language_value.lower(), language_value)

    depth = data.get("depth")

    # Coerce legacy numeric depth values into supported labels so background jobs and older clients do not crash model validation.
    if isinstance(depth, int):
      if depth == 2:
        data["depth"] = "highlights"
      elif depth == 6:
        data["depth"] = "detailed"
      elif depth == 10:
        data["depth"] = "training"
      else:
        raise ValueError("Depth must be Highlights, Detailed, Training, or one of 2, 6, 10.")

    if isinstance(depth, str):
      normalized_depth = _normalize_option_id(depth)
      # Accept numeric string depths used by legacy clients and job payloads.
      if normalized_depth == "2":
        normalized_depth = "highlights"
      elif normalized_depth == "6":
        normalized_depth = "detailed"
      elif normalized_depth == "10":
        normalized_depth = "training"
      data["depth"] = normalized_depth

    widgets = data.get("widgets")

    if isinstance(widgets, list):
      normalized_widgets: list[str] = []

      for widget in widgets:
        # Enforce string-only entries for widget selections.
        if not isinstance(widget, str):
          raise ValueError("Widget entries must be strings.")
        normalized_widgets.append(widget)

      data["widgets"] = _normalize_widget_ids(normalized_widgets)

    return data

  @field_validator("teaching_style")
  @classmethod
  def validate_unique_teaching_styles(cls, teaching_style: list[str]) -> list[str]:
    """Reject duplicate teaching style selections to keep request intent explicit."""
    # Enforce uniqueness so downstream defaults do not receive ambiguous style arrays.
    if len(set(teaching_style)) != len(teaching_style):
      raise ValueError("Teaching style entries must be unique.")
    return teaching_style

  @field_validator("widgets")
  @classmethod
  def validate_unique_widgets(cls, widgets: list[str] | None) -> list[str] | None:
    """Reject duplicate widget selections so each requested widget id is intentional."""
    # Skip uniqueness checks when clients rely on server defaults.
    if widgets is None:
      return widgets
    # Enforce uniqueness after normalization to avoid alias duplicates.
    if len(set(widgets)) != len(widgets):
      raise ValueError("Widget entries must be unique.")
    return widgets

  @model_validator(mode="after")
  def validate_secondary_language_scope(self) -> BaseLessonRequest:
    """Enforce secondary language only for language practice lessons."""
    # Require a target language only when the user selected the language practice blueprint.
    if self.blueprint == "languagepractice" and self.secondary_language is None:
      raise ValueError("secondary_language is required when blueprint is languagepractice.")
    # Reject stray secondary language values for non-language blueprints.
    if self.secondary_language is not None and self.blueprint != "languagepractice":
      raise ValueError("secondary_language is only allowed when blueprint is languagepractice.")
    return self


class GenerateLessonRequest(BaseLessonRequest):
  """Request payload for lesson generation."""

  outcomes: list[OutcomeText] = Field(min_length=1, max_length=8, description="Required outcomes to guide the planner.")


class GenerateOutcomesRequest(BaseLessonRequest):
  """Request payload for outcomes preflight."""


class LessonMeta(BaseModel):
  """Metadata about the lesson generation process."""

  provider_a: StrictStr
  model_a: StrictStr
  provider_b: StrictStr
  model_b: StrictStr
  latency_ms: StrictInt


class LessonOutcomesMeta(BaseModel):
  """Metadata about outcomes generation."""

  provider: StrictStr
  model: StrictStr
  latency_ms: StrictInt


class GenerateLessonResponse(BaseModel):
  """Response payload for lesson generation."""

  lesson_id: StrictStr
  lesson_json: dict[str, Any]
  meta: LessonMeta
  logs: list[StrictStr]  # New field for orchestration logs


class OrchestrationFailureResponse(BaseModel):
  """Response payload for orchestration failures."""

  detail: StrictStr
  error: StrictStr
  logs: list[StrictStr]


class SectionSummary(BaseModel):
  """Summary of a lesson section."""

  section_id: StrictInt
  title: StrictStr
  status: StrictStr


class SectionOutline(BaseModel):
  """Title of a section and its subsections."""

  title: StrictStr
  subsections: list[StrictStr]


class LessonOutlineResponse(BaseModel):
  """Lesson title, topic, and section outline."""

  lesson_id: StrictStr
  topic: StrictStr
  title: StrictStr
  sections: list[SectionOutline]


class LessonRecordResponse(BaseModel):
  """Response payload for lesson retrieval."""

  lesson_id: StrictStr
  topic: StrictStr
  title: StrictStr
  created_at: StrictStr
  sections: list[SectionSummary]


class OptionDetail(BaseModel):
  """Metadata describing an option with tooltip guidance."""

  id: StrictStr
  label: StrictStr
  tooltip: StrictStr


class LessonCatalogResponse(BaseModel):
  """Response payload for lesson option metadata."""

  blueprints: list[OptionDetail]
  teaching_styles: list[OptionDetail]
  learner_levels: list[OptionDetail]
  depths: list[OptionDetail]
  widgets: list[OptionDetail]
  default_widgets: dict[str, dict[str, list[StrictStr]]]


class WritingCheckRequest(BaseModel):
  """Request payload for response evaluation."""

  text: StrictStr = Field(min_length=1, description="The user-written response to check (max 300 words).")
  widget_id: StrictStr | None = Field(default=None, description="Public subsection widget id being checked.")
  criteria: dict[str, Any] | None = Field(default=None, description="Legacy evaluation criteria (deprecated).")
  model_config = ConfigDict(extra="forbid")

  @model_validator(mode="after")
  def validate_check_target(self) -> WritingCheckRequest:
    if self.widget_id is None and self.criteria is None:
      raise ValueError("Either widget_id or criteria must be provided.")
    return self


JobKind = Literal["lesson", "research", "youtube", "maintenance", "writing", "system"]


class JobCreateRequest(BaseModel):
  """Request payload for creating a background job."""

  job_kind: JobKind
  target_agent: StrictStr = Field(min_length=1)
  idempotency_key: StrictStr = Field(min_length=1, description="Client-generated key used to deduplicate submissions.")
  payload: dict[str, Any] = Field(default_factory=dict, description="Agent-specific payload.")
  lesson_id: StrictStr | None = Field(default=None, description="Optional lesson identifier bound to this job.")
  section_id: StrictInt | None = Field(default=None, ge=1, description="Optional section row id bound to this job.")
  parent_job_id: StrictStr | None = Field(default=None, description="Optional parent job id for child job creation.")
  model_config = ConfigDict(extra="forbid")


class JobCreateResponse(BaseModel):
  """Response payload for job creation."""

  job_id: StrictStr
  expected_sections: StrictInt = Field(default=0, ge=0, description="Total number of sections expected for lesson jobs.")


class LessonJobResponse(JobCreateResponse):
  """Response payload for async lesson generation."""

  lesson_id: StrictStr


RetryAgent = Literal["planner", "section_builder", "illustration", "tutor", "fenster_builder"]


class JobRetryRequest(BaseModel):
  """Request payload for retrying a failed job."""

  sections: list[StrictInt] | None = Field(default=None, description="0-based section indexes to retry (defaults to all sections).")
  agents: list[RetryAgent] | None = Field(default=None, description="Pipeline agents to retry (defaults to full pipeline).")
  model_config = ConfigDict(extra="forbid")

  @model_validator(mode="after")
  def validate_retry_targets(self) -> JobRetryRequest:
    # Enforce non-negative section indexes for retry requests.
    if self.sections:
      for index in self.sections:
        if index < 0:
          raise ValueError("Section indexes must be 0 or greater.")

    return self


class CurrentSectionStatus(BaseModel):
  """Section status metadata for streaming job progress."""

  index: StrictInt = Field(ge=0, description="0-based index of the active section.")
  title: StrictStr | None = Field(default=None, description="Title of the active section when known.")
  status: StrictStr = Field(description="Section generation status.")
  retry_count: StrictInt | None = Field(default=None, ge=0, description="Retry attempts for the active section when applicable.")
  model_config = ConfigDict(extra="forbid")


class ChildJobStatus(BaseModel):
  """Status payload for a child job."""

  job_id: StrictStr
  status: JobStatus
  model_config = ConfigDict(extra="forbid")


class JobStatusResponse(BaseModel):
  """Status payload for a background job."""

  job_id: StrictStr
  status: JobStatus
  child_jobs: list[ChildJobStatus] | None = None
  lesson_id: StrictStr | None = None
  requested_job_id: StrictStr | None = None
  resolved_job_id: StrictStr | None = None
  was_superseded: bool = False
  superseded_by_job_id: StrictStr | None = None
  superseded_job_id: StrictStr | None = None
  follow_from_job_id: StrictStr | None = None
  model_config = ConfigDict(populate_by_name=True)
