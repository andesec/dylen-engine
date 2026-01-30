from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, model_validator

from app.jobs.guardrails import MAX_ITEM_BYTES
from app.jobs.models import JobStatus
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


class ModelsConfig(BaseModel):
  """Per-agent model selection overrides."""

  section_builder_model: StrictStr | None = Field(
    default=None,
    validation_alias=AliasChoices("section_builder_model", "gatherer_model", "knowledge_model", "structurer_model"),
    serialization_alias="section_builder_model",
    description="Model used for the section builder agent (provider inferred when possible).",
    examples=["xiaomi/mimo-v2-flash:free"],
  )
  planner_model: StrictStr | None = Field(default=None, description="Model used for the planner agent (provider inferred when possible).", examples=["openai/gpt-oss-120b:free"])
  repairer_model: StrictStr | None = Field(default=None, description="Model used for repair validation and fixes (provider inferred when possible).", examples=["google/gemma-3-27b-it:free"])

  model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GenerateLessonRequest(BaseModel):
  """Request payload for lesson generation."""

  topic: StrictStr = Field(min_length=1, description="Topic to generate a lesson for.", examples=["Introduction to Python"])
  details: StrictStr | None = Field(default=None, min_length=1, max_length=300, description="Optional user-supplied details (max 300 characters).", examples=["Focus on lists and loops"])
  blueprint: Literal["skillbuilding", "knowledgeunderstanding", "communicationskills", "planningandproductivity", "movementandfitness", "growthmindset", "criticalthinking", "creativeskills", "webdevandcoding", "languagepractice"] | None = Field(
    default=None, description="Optional blueprint or learning outcome guidance for lesson planning."
  )
  teaching_style: list[Literal["conceptual", "theoretical", "practical"]] | None = Field(default=None, description="Optional teaching style or pedagogy guidance for lesson planning.")
  learner_level: StrictStr | None = Field(default=None, min_length=1, description="Optional learner level hint used for prompt guidance.")
  depth: Literal["highlights", "detailed", "training"] = Field(default="highlights", description="Requested lesson depth (Highlights=2, Detailed=6, Training=10).")
  primary_language: Literal["English", "German", "Urdu"] = Field(default="English", description="Primary language for lesson output.")
  widgets: list[StrictStr] | None = Field(default=None, min_length=3, max_length=8, description="Optional list of allowed widgets (overrides defaults).")
  schema_version: StrictStr | None = Field(default=None, description="Optional schema version to pin the lesson output to.")
  idempotency_key: StrictStr | None = Field(default=None, description="Idempotency key to prevent duplicate lesson generation.")
  models: ModelsConfig | None = Field(
    default=None, description="Optional per-agent model selection overrides.", examples=[{"section_builder_model": "xiaomi/mimo-v2-flash:free", "planner_model": "openai/gpt-oss-120b:free", "repairer_model": "google/gemma-3-27b-it:free"}]
  )
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

    if isinstance(teaching_style, str):
      teaching_style = [teaching_style]

    if isinstance(teaching_style, list):
      normalized_styles: list[str] = []

      for style in teaching_style:
        # Enforce string-only entries for teaching styles.
        if not isinstance(style, str):
          raise ValueError("Teaching style entries must be strings.")
        normalized_styles.append(_normalize_option_id(style))

      # Expand legacy "all" into the explicit style list.
      if "all" in normalized_styles:
        normalized_styles = ["conceptual", "theoretical", "practical"]

      data["teaching_style"] = normalized_styles

    learner_level = data.get("learner_level")

    if isinstance(learner_level, str):
      data["learner_level"] = _normalize_option_id(learner_level)

    depth = data.get("depth")

    if isinstance(depth, str):
      data["depth"] = _normalize_option_id(depth)

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

  @model_validator(mode="after")
  def validate_depth_style_constraint(self) -> GenerateLessonRequest:
    if self.depth == "highlights" and self.teaching_style:
      if len(self.teaching_style) == 3:
        raise ValueError("Cannot select all teaching styles when depth is 'highlights'.")
    return self


class LessonMeta(BaseModel):
  """Metadata about the lesson generation process."""

  provider_a: StrictStr
  model_a: StrictStr
  provider_b: StrictStr
  model_b: StrictStr
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


class LessonRecordResponse(BaseModel):
  """Response payload for lesson retrieval."""

  lesson_id: StrictStr
  topic: StrictStr
  title: StrictStr
  created_at: StrictStr
  schema_version: StrictStr
  prompt_version: StrictStr
  lesson_json: dict[str, Any]
  meta: LessonMeta


class OptionDetail(BaseModel):
  """Metadata describing an option with tooltip guidance."""

  id: StrictStr
  label: StrictStr
  tooltip: StrictStr


class AgentModelOption(BaseModel):
  """Valid model choices for a pipeline agent."""

  agent: StrictStr
  default: StrictStr | None
  options: list[StrictStr]


class LessonCatalogResponse(BaseModel):
  """Response payload for lesson option metadata."""

  blueprints: list[OptionDetail]
  teaching_styles: list[OptionDetail]
  learner_levels: list[OptionDetail]
  depths: list[OptionDetail]
  widgets: list[OptionDetail]
  agent_models: list[AgentModelOption]
  default_widgets: dict[str, dict[str, list[StrictStr]]]


class WritingCheckRequest(BaseModel):
  """Request payload for response evaluation."""

  text: StrictStr = Field(min_length=1, description="The user-written response to check (max 300 words).")
  criteria: dict[str, Any] = Field(description="The evaluation criteria from the lesson.")
  checker_model: StrictStr | None = Field(default=None, description="Optional model override for writing evaluation (provider inferred when possible).", examples=["openai/gpt-oss-120b:free"])
  idempotency_key: StrictStr | None = Field(default=None, description="Idempotency key to prevent duplicate requests.")
  model_config = ConfigDict(extra="forbid")


class JobCreateResponse(BaseModel):
  """Response payload for job creation."""

  job_id: StrictStr
  expected_sections: StrictInt = Field(ge=0, description="Total number of sections expected for the lesson job (0 for non-lesson jobs).")


RetryAgent = Literal["planner", "section_builder", "repair", "stitcher"]


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


class JobStatusResponse(BaseModel):
  """Status payload for an asynchronous job."""

  job_id: StrictStr
  status: JobStatus
  phase: StrictStr | None = None
  subphase: StrictStr | None = None
  expected_sections: StrictInt | None = Field(default=None, ge=0, description="Total number of expected sections for lesson jobs.")
  completed_sections: StrictInt | None = Field(default=None, ge=0, description="Number of lesson sections completed so far.")
  completed_section_indexes: list[StrictInt] | None = Field(default=None, description="0-based section indexes that have been completed so far.")
  current_section: CurrentSectionStatus | None = None
  retry_count: StrictInt | None = Field(default=None, ge=0, description="Retry attempts already used for this job.")
  max_retries: StrictInt | None = Field(default=None, ge=0, description="Maximum retry attempts allowed for this job.")
  retry_sections: list[StrictInt] | None = Field(default=None, description="0-based section indexes targeted for retry, when applicable.")
  retry_agents: list[StrictStr] | None = Field(default=None, description="Pipeline agents targeted for retry, when applicable.")
  total_steps: StrictInt | None = Field(default=None, ge=1, description="Total number of progress steps when available.")
  completed_steps: StrictInt | None = Field(default=None, ge=0, description="Completed progress steps when available.")
  progress: StrictFloat | None = Field(default=None, ge=0.0, le=100.0, description="Progress percent (0-100) when available.")
  logs: list[StrictStr] = Field(default_factory=list)
  result: dict[str, Any] | None = None
  validation: ValidationResponse | None = None
  cost: dict[str, Any] | None = None
  created_at: StrictStr
  updated_at: StrictStr
  completed_at: StrictStr | None = Field(default=None)
  model_config = ConfigDict(populate_by_name=True)
