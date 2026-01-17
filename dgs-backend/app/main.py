from __future__ import annotations

import json
import asyncio
import logging
import sys
import time
from functools import lru_cache
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import (
  AliasChoices,
  BaseModel,
  ConfigDict,
  Field,
  StrictFloat,
  StrictInt,
  StrictStr,
  ValidationError,
  model_validator,
)
from starlette.concurrency import run_in_threadpool

from app.ai.orchestrator import DgsOrchestrator, OrchestrationError
from app.config import Settings, get_settings
from app.jobs.guardrails import MAX_ITEM_BYTES, estimate_bytes
from app.jobs.models import JobRecord, JobStatus
from app.schema.lesson_catalog import build_lesson_catalog
from app.schema.serialize_lesson import lesson_to_shorthand
from app.schema.validate_lesson import validate_lesson
from app.storage.lessons_repo import LessonRecord, LessonsRepository
from app.storage.jobs_repo import JobsRepository
from app.storage.postgres_jobs_repo import PostgresJobsRepository
from app.storage.postgres_lessons_repo import PostgresLessonsRepository
from app.utils.ids import generate_job_id, generate_lesson_id

settings = get_settings()
# Track background job worker state for lifecycle management.
_JOB_WORKER_TASK: asyncio.Task[None] | None = None
_JOB_WORKER_ACTIVE = False


class DecimalJSONEncoder(json.JSONEncoder):
  """Custom JSON encoder that handles Decimal types from DynamoDB."""
  
  def default(self, obj: Any) -> Any:
    if isinstance(obj, Decimal):
      return int(obj) if obj % 1 == 0 else float(obj)
    return super().default(obj)


class DecimalJSONResponse(JSONResponse):
  """Custom JSONResponse that uses DecimalJSONEncoder."""
  
  def render(self, content: Any) -> bytes:
    return json.dumps(
      content,
      ensure_ascii=False,
      allow_nan=False,
      indent=None,
      separators=(",", ":"),
      cls=DecimalJSONEncoder,
    ).encode("utf-8")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  """Ensure logging is correctly set up after uvicorn starts."""
  
  try:
    _initialize_logging()
    logger.info("Startup complete - logging verified.")
    
    _start_job_worker(settings)
  
  except Exception:
    logger.warning("Initial logging setup failed; will retry on lifespan.", exc_info=True)
  
  yield
  
  _stop_job_worker()


app = FastAPI(default_response_class=DecimalJSONResponse, lifespan=lifespan)

app.add_middleware(
  CORSMiddleware,
  allow_origins=settings.allowed_origins,
  allow_credentials=False,
  allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
  allow_headers=["content-type", "authorization", "x-dgs-dev-key"],
  expose_headers=["content-length"],
)


def _error_payload(detail: str, *, error: str | None = None, logs: list[str] | None = None) -> dict[str, Any]:
  """Build error payloads with optional debug detail."""
  payload = {"detail": detail}

  # Only attach diagnostic details when debug mode is enabled.
  if settings.debug:

    if error is not None:
      payload["error"] = error

    if logs is not None:
      payload["logs"] = logs


  return payload


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> DecimalJSONResponse:
  """Global exception handler to catch unhandled errors."""
  logger = logging.getLogger("uvicorn.error")
  logger.error(f"Global exception: {exc}", exc_info=True)
  return DecimalJSONResponse(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    content=_error_payload("Internal Server Error", error=str(exc)),
  )

@app.exception_handler(OrchestrationError)
async def orchestration_exception_handler(request: Request, exc: OrchestrationError) -> DecimalJSONResponse:
  """Return a structured failure response for orchestration errors."""
  # Log orchestration failures with stack traces for diagnostics.
  logger = logging.getLogger("uvicorn.error")
  logger.error("Orchestration failure: %s", exc, exc_info=True)
  # Provide the failure logs so callers can close out the request with context.
  return DecimalJSONResponse(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    content=_error_payload("Orchestration failed", error=str(exc), logs=exc.logs),
  )


LOG_LINE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LINE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
LOG_FORMATTER = logging.Formatter(LOG_LINE_FORMAT, datefmt=LOG_DATE_FORMAT)
_LOG_FILE_PATH: Path | None = None
_LOGGING_INITIALIZED = False

_JOB_NOT_FOUND_MSG = "Job not found."
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"




class TruncatedFormatter(logging.Formatter):
  """Formatter that truncates the stack trace to the last few lines."""
  
  # ruff: noqa: N802
  def formatException(
      self,
      ei: tuple[type[BaseException] | None, BaseException | None, TracebackType | None],
  ) -> str:
    import traceback
    
    lines = traceback.format_exception(*ei)
    # Keep header + last 5 lines of traceback
    if len(lines) > 6:
      return "".join(lines[:1] + ["    ...\n"] + lines[-5:])
    return "".join(lines)


def _build_handlers() -> tuple[logging.Handler, logging.Handler, Path]:
  """Create logging handlers anchored to the backend directory."""
  log_dir = Path(__file__).resolve().parent.parent / "logs"
  try:
    log_dir.mkdir(parents=True, exist_ok=True)
  except OSError as exc:
    raise RuntimeError(f"Failed to create log directory at {log_dir}: {exc}") from exc
  
  log_path = log_dir / f"dgs_app_{time.strftime('%Y%m%d_%H%M%S')}.log"
  try:
    # Touch early so the file exists even if handlers have not flushed yet.
    log_path.touch(exist_ok=True)
  except OSError as exc:
    raise RuntimeError(f"Failed to create log file at {log_path}: {exc}") from exc
  
  stream = logging.StreamHandler(sys.stdout)
  stream.setFormatter(TruncatedFormatter(LOG_LINE_FORMAT, datefmt="%H:%M:%S"))
  file_handler = logging.FileHandler(log_path, encoding="utf-8")
  file_handler.setFormatter(LOG_FORMATTER)
  return stream, file_handler, log_path


def setup_logging() -> Path:
  """Ensure all loggers use our handlers and propagate to root."""
  stream_handler, file_handler, log_path = _build_handlers()
  for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
    l = logging.getLogger(logger_name)
    l.handlers = [stream_handler, file_handler]
    l.propagate = False
  
  logging.basicConfig(level=logging.DEBUG, handlers=[stream_handler, file_handler], force=True)
  root = logging.getLogger()
  root.setLevel(logging.DEBUG)
  if not root.handlers:
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
  if not log_path.exists():
    raise RuntimeError(f"Logging initialization failed; log file missing at {log_path}")
  return log_path


# Silence noisy libraries
logging.getLogger("urllib3").setLevel(logging.ERROR)

logger = logging.getLogger("app.main")


def _log_widget_registry() -> None:
  rules_path = Path(__file__).parent / "schema" / "widgets_prompt.md"
  try:
    from app.schema.widgets_loader import load_widget_registry
    
    registry = load_widget_registry(rules_path)
  except (FileNotFoundError, PermissionError, UnicodeDecodeError, ValueError) as exc:
    logger.warning("Failed to load widget registry from %s: %s", rules_path, exc)
    return
  
  widget_names = registry.available_types()
  logger.info(
    "Widget registry loaded from %s (%d types): %s",
    rules_path,
    len(widget_names),
    ", ".join(widget_names),
  )


def _initialize_logging() -> None:
  """Initialize logging and log startup messages."""
  global _LOG_FILE_PATH, _LOGGING_INITIALIZED
  if _LOGGING_INITIALIZED:
    return
  log_path = setup_logging()
  _LOG_FILE_PATH = log_path
  _LOGGING_INITIALIZED = True
  logger.info("Logging initialized. Writing to %s", _LOG_FILE_PATH)
  _log_widget_registry()


def _start_job_worker(active_settings: Settings) -> None:
  """Start a lightweight job poller to ensure queued jobs are processed."""
  global _JOB_WORKER_TASK, _JOB_WORKER_ACTIVE
  
  # Avoid spawning multiple loops if lifespan runs more than once.
  
  if _JOB_WORKER_ACTIVE:
    return
  
  if not active_settings.jobs_auto_process:
    return
  
  # Schedule the worker on the running loop so it survives request lifetimes.
  
  loop = asyncio.get_running_loop()
  _JOB_WORKER_TASK = loop.create_task(_job_worker_loop(active_settings))
  _JOB_WORKER_TASK.add_done_callback(_log_job_task_failure)
  _JOB_WORKER_ACTIVE = True
  logger.info("Job worker loop started.")


def _stop_job_worker() -> None:
  """Stop the job poller when the app shuts down."""
  global _JOB_WORKER_TASK, _JOB_WORKER_ACTIVE
  
  if not _JOB_WORKER_ACTIVE:
    return
  
  if _JOB_WORKER_TASK is None:
    _JOB_WORKER_ACTIVE = False
    return
  
  # Cancel the task to stop polling promptly on shutdown.
  
  _JOB_WORKER_TASK.cancel()
  _JOB_WORKER_TASK = None
  _JOB_WORKER_ACTIVE = False
  logger.info("Job worker loop stopped.")


async def _job_worker_loop(active_settings: Settings) -> None:
  """Poll for queued jobs so processing happens even if kickoff is missed."""
  from app.jobs.worker import JobProcessor
  
  # Reuse a single processor to keep orchestration wiring consistent.
  
  repo = _get_jobs_repo(active_settings)
  processor = JobProcessor(
    jobs_repo=repo,
    orchestrator=_get_orchestrator(active_settings),
    settings=active_settings,
  )
  poll_seconds = 2.0
  
  while True:
    
    try:
      await processor.process_queue(limit=5)
    
    
    except Exception as exc:  # noqa: BLE001
      logger.error("Job worker loop failed: %s", exc, exc_info=True)
    
    await asyncio.sleep(poll_seconds)


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
  """Log all incoming requests and outgoing responses."""
  start_time = time.time()
  logger.info(f"Incoming request: {request.method} {request.url}")
  
  try:
    if request.headers.get("content-type") == "application/json":
      body = await request.body()
      if body:
        logger.debug(f"Request Body: {body.decode('utf-8')}")
  except Exception:
    pass  # Don't fail if body logging fails
  
  response = await call_next(request)
  
  process_time = (time.time() - start_time) * 1000
  logger.info(f"Response: {response.status_code} (took {process_time:.2f}ms)")
  return response


class ValidationResponse(BaseModel):
  """Response model for lesson validation results."""
  
  ok: bool
  errors: list[str]


class KnowledgeModel(str, Enum):
  """Model options for the knowledge collection agent."""
  
  GEMINI_25_FLASH = "gemini-2.5-flash"
  GEMINI_25_PRO = "gemini-2.5-pro"
  XIAOMI_MIMO_V2_FLASH = "xiaomi/mimo-v2-flash:free"
  DEEPSEEK_R1_0528 = "deepseek/deepseek-r1-0528:free"
  LLAMA_31_405B = "meta-llama/llama-3.1-405b-instruct:free"
  GPT_OSS_120B = "openai/gpt-oss-120b:free"


class StructurerModel(str, Enum):
  """Model options for the structuring agent."""
  
  GEMMA_3_27B = "google/gemma-3-27b-it:free"
  GEMINI_25_FLASH = "gemini-2.5-flash"
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


class GathererStructurerModel(str, Enum):
  """Model options for the merged gatherer+structurer agent."""
  
  GEMINI_25_FLASH = "gemini-2.5-flash"
  GEMINI_25_PRO = "gemini-2.5-pro"
  XIAOMI_MIMO_V2_FLASH = "xiaomi/mimo-v2-flash:free"
  DEEPSEEK_R1_0528 = "deepseek/deepseek-r1-0528:free"
  LLAMA_31_405B = "meta-llama/llama-3.1-405b-instruct:free"
  GPT_OSS_120B = "openai/gpt-oss-120b:free"


class ModelsConfig(BaseModel):
  """Per-agent model selection overrides."""
  
  gatherer_model: StrictStr | None = Field(
    default=None,
    validation_alias=AliasChoices("gatherer_model", "knowledge_model"),
    serialization_alias="gatherer_model",
    description="Model used for the gatherer agent (provider inferred when possible).",
    examples=["xiaomi/mimo-v2-flash:free"],
  )
  planner_model: StrictStr | None = Field(
    default=None,
    description="Model used for the planner agent (provider inferred when possible).",
    examples=["openai/gpt-oss-120b:free"],
  )
  structurer_model: StrictStr | None = Field(
    default=None,
    description="Model used for lesson structuring (provider inferred when possible).",
    examples=["openai/gpt-oss-20b:free"],
  )
  repairer_model: StrictStr | None = Field(
    default=None,
    description="Model used for repair validation and fixes (provider inferred when possible).",
    examples=["google/gemma-3-27b-it:free"],
  )
  
  model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GenerateLessonRequest(BaseModel):
  """Request payload for lesson generation."""
  
  topic: StrictStr = Field(
    min_length=1,
    description="Topic to generate a lesson for.",
    examples=["Introduction to Python"],
  )
  details: StrictStr | None = Field(
    default=None,
    min_length=1,
    description="Optional user-supplied details (max 250 words).",
    examples=["Focus on lists and loops"],
  )
  blueprint: (
      Literal[
        "skillbuilding",
        "knowledgeunderstanding",
        "communicationskills",
        "planningandproductivity",
        "movementandfitness",
        "growthmindset",
        "criticalthinking",
        "creativeskills",
        "webdevandcoding",
        "languagepractice",
      ]
      | None
  ) = Field(
    default=None,
    description="Optional blueprint or learning outcome guidance for lesson planning.",
  )
  teaching_style: list[Literal["conceptual", "theoretical", "practical"]] | None = Field(
    default=None,
    description="Optional teaching style or pedagogy guidance for lesson planning.",
  )
  learner_level: StrictStr | None = Field(
    default=None,
    min_length=1,
    description="Optional learner level hint used for prompt guidance.",
  )
  depth: Literal["highlights", "detailed", "training"] = Field(
    default="highlights",
    description="Requested lesson depth (Highlights=2, Detailed=6, Training=10).",
  )
  primary_language: Literal["English", "German", "Urdu"] = Field(
    default="English",
    description="Primary language for lesson output.",
  )
  widgets: list[StrictStr] | None = Field(
    default=None,
    min_length=3,
    max_length=8,
    description="Optional list of allowed widgets (overrides defaults).",
  )
  schema_version: StrictStr | None = Field(
    default=None, description="Optional schema version to pin the lesson output to."
  )
  idempotency_key: StrictStr | None = Field(
    default=None,
    description="Idempotency key to prevent duplicate lesson generation.",
  )
  models: ModelsConfig | None = Field(
    default=None,
    description="Optional per-agent model selection overrides.",
    examples=[
      {
        "gatherer_model": "xiaomi/mimo-v2-flash:free",
        "planner_model": "openai/gpt-oss-120b:free",
        "structurer_model": "openai/gpt-oss-20b:free",
        "repairer_model": "google/gemma-3-27b-it:free",
      }
    ],
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
  
  text: StrictStr = Field(
    min_length=1, description="The user-written response to check (max 300 words)."
  )
  criteria: dict[str, Any] = Field(description="The evaluation criteria from the lesson.")
  checker_model: StrictStr | None = Field(
    default=None,
    description="Optional model override for writing evaluation (provider inferred when possible).",
    examples=["openai/gpt-oss-20b:free"],
  )
  model_config = ConfigDict(extra="forbid")


class JobCreateResponse(BaseModel):
  """Response payload for job creation."""
  
  job_id: StrictStr
  expected_sections: StrictInt = Field(
    ge=0,
    description="Total number of sections expected for the lesson job (0 for non-lesson jobs).",
  )


RetryAgent = Literal["planner", "gatherer", "structurer", "repair", "stitcher"]


class JobRetryRequest(BaseModel):
  """Request payload for retrying a failed job."""
  
  sections: list[StrictInt] | None = Field(
    default=None,
    description="0-based section indexes to retry (defaults to all sections).",
  )
  agents: list[RetryAgent] | None = Field(
    default=None,
    description="Pipeline agents to retry (defaults to full pipeline).",
  )
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
  retry_count: StrictInt | None = Field(
    default=None,
    ge=0,
    description="Retry attempts for the active section when applicable.",
  )
  model_config = ConfigDict(extra="forbid")


class JobStatusResponse(BaseModel):
  """Status payload for an asynchronous job."""
  
  job_id: StrictStr
  status: JobStatus
  phase: StrictStr | None = None
  subphase: StrictStr | None = None
  expected_sections: StrictInt | None = Field(
    default=None,
    ge=0,
    description="Total number of expected sections for lesson jobs.",
  )
  completed_sections: StrictInt | None = Field(
    default=None,
    ge=0,
    description="Number of lesson sections completed so far.",
  )
  completed_section_indexes: list[StrictInt] | None = Field(
    default=None,
    description="0-based section indexes that have been completed so far.",
  )
  current_section: CurrentSectionStatus | None = None
  retry_count: StrictInt | None = Field(
    default=None,
    ge=0,
    description="Retry attempts already used for this job.",
  )
  max_retries: StrictInt | None = Field(
    default=None,
    ge=0,
    description="Maximum retry attempts allowed for this job.",
  )
  retry_sections: list[StrictInt] | None = Field(
    default=None,
    description="0-based section indexes targeted for retry, when applicable.",
  )
  retry_agents: list[StrictStr] | None = Field(
    default=None,
    description="Pipeline agents targeted for retry, when applicable.",
  )
  total_steps: StrictInt | None = Field(
    default=None,
    ge=1,
    description="Total number of progress steps when available.",
  )
  completed_steps: StrictInt | None = Field(
    default=None,
    ge=0,
    description="Completed progress steps when available.",
  )
  progress: StrictFloat | None = Field(
    default=None,
    ge=0.0,
    le=100.0,
    description="Progress percent (0-100) when available.",
  )
  logs: list[StrictStr] = Field(default_factory=list)
  result: dict[str, Any] | None = None
  validation: ValidationResponse | None = None
  cost: dict[str, Any] | None = None
  created_at: StrictStr
  updated_at: StrictStr
  completed_at: StrictStr | None = Field(
    default=None
  )
  model_config = ConfigDict(populate_by_name=True)


MAX_REQUEST_BYTES = MAX_ITEM_BYTES // 2


def _normalize_option_id(value: str) -> str:
  """Normalize option ids to lowercase alphanumeric tokens."""
  # Strip non-alphanumeric characters for stable option ids.
  return "".join(ch for ch in value.lower() if ch.isalnum())


@lru_cache(maxsize=1)
def _widget_id_map() -> dict[str, str]:
  """Build a mapping from normalized widget ids to canonical widget keys."""
  # Load widget registry once to align client ids with schema keys.
  from app.schema.service import DEFAULT_WIDGETS_PATH
  from app.schema.widgets_loader import load_widget_registry

  registry = load_widget_registry(DEFAULT_WIDGETS_PATH)
  mapping: dict[str, str] = {}

  for widget_name in registry.available_types():
    normalized = _normalize_option_id(widget_name)
    mapping[normalized] = widget_name

  return mapping


def _normalize_widget_ids(widgets: list[str]) -> list[str]:
  """Normalize widget ids to canonical registry keys."""
  widget_map = _widget_id_map()
  normalized: list[str] = []

  for widget in widgets:
    # Normalize widget ids so schema validation uses canonical keys.
    widget_id = _normalize_option_id(widget)

    if widget_id not in widget_map:
      raise ValueError(f"Unsupported widget id '{widget}'.")

    normalized.append(widget_map[widget_id])

  return normalized


def _get_orchestrator(
    settings: Settings,
    *,
    gatherer_provider: str | None = None,
    gatherer_model: str | None = None,
    planner_provider: str | None = None,
    planner_model: str | None = None,
    structurer_provider: str | None = None,
    structurer_model: str | None = None,
    repair_provider: str | None = None,
    repair_model: str | None = None,
) -> DgsOrchestrator:
  return DgsOrchestrator(
    gatherer_provider=gatherer_provider or settings.gatherer_provider,
    gatherer_model=gatherer_model or settings.gatherer_model,
    planner_provider=planner_provider or settings.planner_provider,
    planner_model=planner_model or settings.planner_model,
    structurer_provider=structurer_provider or settings.structurer_provider,
    structurer_model=structurer_model or settings.structurer_model,
    repair_provider=repair_provider or settings.repair_provider,
    repair_model=repair_model or settings.repair_model,
    schema_version=settings.schema_version,
    merge_gatherer_structurer=settings.merge_gatherer_structurer,
  )


def _get_repo(settings: Settings) -> LessonsRepository:
  """Return the active lessons repository."""
  
  # Enforce Postgres-backed storage for lessons.
  
  if not settings.pg_dsn:
    raise ValueError("DGS_PG_DSN must be set to enable Postgres persistence.")
  
  return PostgresLessonsRepository(
    dsn=settings.pg_dsn,
    connect_timeout=settings.pg_connect_timeout,
    table_name=settings.pg_lessons_table,
  )


def _get_jobs_repo(settings: Settings) -> JobsRepository:
  """Return the active jobs repository."""
  
  # Enforce Postgres-backed storage for jobs.
  
  if not settings.pg_dsn:
    raise ValueError("DGS_PG_DSN must be set to enable Postgres persistence.")
  
  return PostgresJobsRepository(
    dsn=settings.pg_dsn,
    connect_timeout=settings.pg_connect_timeout,
    table_name=settings.pg_jobs_table,
  )


_GEMINI_PROVIDER = "gemini"
_OPENROUTER_PROVIDER = "openrouter"

_GEMINI_KNOWLEDGE_MODELS = {
  KnowledgeModel.GEMINI_25_FLASH,
  KnowledgeModel.GEMINI_25_PRO,
}

_OPENROUTER_KNOWLEDGE_MODELS = {
  KnowledgeModel.XIAOMI_MIMO_V2_FLASH,
  KnowledgeModel.DEEPSEEK_R1_0528,
  KnowledgeModel.LLAMA_31_405B,
  KnowledgeModel.GPT_OSS_120B,
}

_GEMINI_STRUCTURER_MODELS = {StructurerModel.GEMINI_25_FLASH}

_OPENROUTER_STRUCTURER_MODELS = {
  StructurerModel.GPT_OSS_20B,
  StructurerModel.LLAMA_33_70B,
  StructurerModel.GEMMA_3_27B,
}

_GEMINI_PLANNER_MODELS = {
  PlannerModel.GEMINI_25_PRO,
  PlannerModel.GEMINI_PRO_LATEST,
}

_OPENROUTER_PLANNER_MODELS = {
  PlannerModel.GPT_OSS_120B,
  PlannerModel.XIAOMI_MIMO_V2_FLASH,
  PlannerModel.LLAMA_31_405B,
  PlannerModel.DEEPSEEK_R1_0528,
}

_GEMINI_REPAIRER_MODELS = {
  RepairerModel.GEMINI_25_FLASH,
}

_OPENROUTER_REPAIRER_MODELS = {
  RepairerModel.GPT_OSS_20B,
  RepairerModel.GEMMA_3_27B,
  RepairerModel.DEEPSEEK_R1_0528,
}

DEFAULT_KNOWLEDGE_MODEL = KnowledgeModel.LLAMA_31_405B.value


def _resolve_model_selection(
    settings: Settings,
    *,
    models: ModelsConfig | None,
) -> tuple[str, str | None, str, str | None, str, str | None, str, str | None]:
  """
  Derive gatherer and structurer providers/models based on request settings.

  Falls back to environment defaults when user input is missing.
  """
  # Respect per-agent overrides when provided, otherwise use environment defaults.
  
  if models is not None:
    gatherer_model = models.gatherer_model or settings.gatherer_model or DEFAULT_KNOWLEDGE_MODEL
    planner_model = models.planner_model or settings.planner_model
    structurer_model = models.structurer_model or settings.structurer_model
    repairer_model = models.repairer_model or settings.repair_model
  
  else:
    gatherer_model = settings.gatherer_model or DEFAULT_KNOWLEDGE_MODEL
    planner_model = settings.planner_model
    structurer_model = settings.structurer_model
    repairer_model = settings.repair_model
  
  # Resolve provider hints to keep routing consistent for each agent.
  gatherer_provider = _provider_for_knowledge_model(settings, gatherer_model)
  planner_provider = _provider_for_model_hint(planner_model, settings.planner_provider)
  structurer_provider = _provider_for_structurer_model(settings, structurer_model)
  repairer_provider = _provider_for_model_hint(repairer_model, settings.repair_provider)
  return (
    gatherer_provider,
    gatherer_model,
    planner_provider,
    planner_model,
    structurer_provider,
    structurer_model,
    repairer_provider,
    repairer_model,
  )


def _provider_for_knowledge_model(settings: Settings, model_name: str | None) -> str:
  # Keep provider routing consistent even if the model list evolves.
  if not model_name:
    return settings.gatherer_provider
  if model_name in {model.value for model in _GEMINI_KNOWLEDGE_MODELS}:
    return _GEMINI_PROVIDER
  if model_name in {model.value for model in _OPENROUTER_KNOWLEDGE_MODELS}:
    return _OPENROUTER_PROVIDER
  return settings.gatherer_provider


def _provider_for_structurer_model(settings: Settings, model_name: str | None) -> str:
  # Keep provider routing consistent even if the model list evolves.
  
  if not model_name:
    return settings.structurer_provider
  
  if model_name in {model.value for model in _GEMINI_STRUCTURER_MODELS}:
    return _GEMINI_PROVIDER
  
  if model_name in {model.value for model in _OPENROUTER_STRUCTURER_MODELS}:
    return _OPENROUTER_PROVIDER
  
  return settings.structurer_provider


def _provider_for_model_hint(model_name: str | None, fallback_provider: str) -> str:
  """Resolve a provider from known model lists with a safe fallback."""
  # Only route to known providers when the model name matches a known set.
  
  if not model_name:
    return fallback_provider
  
  gemini_models = (
    {model.value for model in _GEMINI_KNOWLEDGE_MODELS}
    | {model.value for model in _GEMINI_STRUCTURER_MODELS}
    | {model.value for model in _GEMINI_PLANNER_MODELS}
    | {model.value for model in _GEMINI_REPAIRER_MODELS}
  )
  openrouter_models = (
    {model.value for model in _OPENROUTER_KNOWLEDGE_MODELS}
    | {model.value for model in _OPENROUTER_STRUCTURER_MODELS}
    | {model.value for model in _OPENROUTER_PLANNER_MODELS}
    | {model.value for model in _OPENROUTER_REPAIRER_MODELS}
  )
  
  if model_name in gemini_models:
    return _GEMINI_PROVIDER
  
  if model_name in openrouter_models:
    return _OPENROUTER_PROVIDER
  
  return fallback_provider


def _require_dev_key(  # noqa: B008
    x_dgs_dev_key: str = Header(..., alias="X-DGS-Dev-Key"),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
  if x_dgs_dev_key != settings.dev_key:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev key.")


def _count_words(text: str) -> int:
  """Approximate word count by splitting on whitespace."""
  return len(text.split())


def _validate_generate_request(request: GenerateLessonRequest, settings: Settings) -> None:
  """Enforce topic/detail length and persistence size constraints."""
  if len(request.topic) > settings.max_topic_length:
    raise HTTPException(
      status_code=status.HTTP_400_BAD_REQUEST,
      detail=f"Topic exceeds max length of {settings.max_topic_length} chars.",
    )
  if request.details:
    # Guardrail to keep user-provided detail payloads within size limits.
    word_count = _count_words(request.details)
    if word_count > 250:
      raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"User details are too long ({word_count} words). Max 250 words.",
      )
  if estimate_bytes(request.model_dump(mode="python", by_alias=True)) > MAX_REQUEST_BYTES:
    raise HTTPException(
      status_code=status.HTTP_400_BAD_REQUEST,
      detail="Request payload is too large for persistence.",
    )
  
  try:
    from app.jobs.progress import build_call_plan  # Local import to avoid circular deps
    
    build_call_plan(
      request.model_dump(mode="python", by_alias=True),
      merge_gatherer_structurer=settings.merge_gatherer_structurer,
    )
  except ValueError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _validate_writing_request(request: WritingCheckRequest) -> None:
  """Validate writing check inputs."""
  word_count = _count_words(request.text)
  if word_count > 300:
    raise HTTPException(
      status_code=status.HTTP_400_BAD_REQUEST,
      detail=f"User text is too long ({word_count} words). Max 300 words.",
    )
  if not request.criteria:
    raise HTTPException(
      status_code=status.HTTP_400_BAD_REQUEST,
      detail="Evaluation criteria are required.",
    )
  if estimate_bytes(request.model_dump(mode="python")) > MAX_REQUEST_BYTES:
    raise HTTPException(
      status_code=status.HTTP_400_BAD_REQUEST,
      detail="Request payload is too large for persistence.",
    )


def _resolve_primary_language(request: GenerateLessonRequest) -> str | None:
  """Return the requested primary language for orchestration prompts."""
  # This feeds prompt guidance but does not change response schema.
  return request.primary_language


def _resolve_learner_level(request: GenerateLessonRequest) -> str | None:
  """Return the learner level from the request."""
  # Prefer the explicit request field for prompt guidance.
  if request.learner_level:
    return request.learner_level
  return None


def _compute_job_ttl(settings: Settings) -> int | None:
  if settings.jobs_ttl_seconds is None:
    return None
  return int(time.time()) + settings.jobs_ttl_seconds


def _job_status_from_record(record: JobRecord) -> JobStatusResponse:
  """Convert a persisted job record into an API response payload."""
  
  # Parse the stored payload into the correct request model for the job type.
  try:
    request = _parse_job_request(record.request)
  
  except ValidationError as exc:
    raise HTTPException(
      status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
      detail="Stored job request failed validation.",
    ) from exc
  
  validation = None
  
  if record.validation is not None:
    validation = ValidationResponse.model_validate(record.validation)
  
  expected_sections = record.expected_sections
  
  # Backfill expected section counts for legacy job records.
  if expected_sections is None and isinstance(request, GenerateLessonRequest):
    expected_sections = _expected_sections_from_request(request)
  
  if expected_sections is None and isinstance(request, WritingCheckRequest):
    expected_sections = 0
  
  current_section = None
  
  if record.current_section_index is not None and record.current_section_status is not None:
    current_section = CurrentSectionStatus(
      index=record.current_section_index,
      title=record.current_section_title,
      status=record.current_section_status,
      retry_count=record.current_section_retry_count,
    )
  
  return JobStatusResponse(
    job_id=record.job_id,
    status=record.status,
    phase=record.phase,
    subphase=record.subphase,
    expected_sections=expected_sections,
    completed_sections=record.completed_sections,
    completed_section_indexes=record.completed_section_indexes,
    current_section=current_section,
    retry_count=record.retry_count,
    max_retries=record.max_retries,
    retry_sections=record.retry_sections,
    retry_agents=record.retry_agents,
    total_steps=record.total_steps,
    completed_steps=record.completed_steps,
    progress=record.progress,
    logs=record.logs or [],
    result=record.result_json,
    validation=validation,
    cost=record.cost,
    created_at=record.created_at,
    updated_at=record.updated_at,
    completed_at=record.completed_at,
  )


def _parse_job_request(payload: dict[str, Any]) -> GenerateLessonRequest | WritingCheckRequest:
  """Resolve the stored job request to the correct request model."""
  
  # Writing checks carry a distinct payload shape (text + criteria).
  
  if "text" in payload and "criteria" in payload:
    return WritingCheckRequest.model_validate(payload)
  
  # Drop deprecated fields so legacy records can still be parsed.
  if "mode" in payload:
    payload = {key: value for key, value in payload.items() if key != "mode"}
  
  return GenerateLessonRequest.model_validate(payload)


def _expected_sections_from_request(request: GenerateLessonRequest) -> int:
  """Compute the expected section count for a lesson job."""
  # Reuse the call plan depth so expected section counts match worker planning.
  from app.jobs.progress import build_call_plan
  
  plan = build_call_plan(
    request.model_dump(mode="python", by_alias=True),
    merge_gatherer_structurer=settings.merge_gatherer_structurer,
  )
  return plan.depth


@app.get("/health")
async def health() -> dict[str, str]:
  return {"status": "ok"}


@app.get(
  "/v1/lessons/catalog",
  response_model=LessonCatalogResponse,
)
async def get_lesson_catalog(response: Response) -> LessonCatalogResponse:
  """Return blueprint, teaching style, and widget metadata for clients."""
  # Toggle cache control with an environment flag for dynamic refreshes.
  if settings.cache_lesson_catalog:
    response.headers["Cache-Control"] = "public, max-age=86400"
  # Build a static payload so the client can cache the response safely.
  payload = build_lesson_catalog(settings)
  return LessonCatalogResponse(**payload)


@app.post(
  "/v1/lessons/validate",
  response_model=ValidationResponse,
  dependencies=[Depends(_require_dev_key)],
)
async def validate_endpoint(payload: dict[str, Any]) -> ValidationResponse:
  """Validate lesson payloads from stored lessons or job results against schema and widgets."""
  
  ok, errors, _model = validate_lesson(payload)
  return ValidationResponse(ok=ok, errors=errors)


@app.post(
  "/v1/lessons/generate",
  response_model=GenerateLessonResponse,
  responses={500: {"model": OrchestrationFailureResponse}},
  dependencies=[Depends(_require_dev_key)],
)
async def generate_lesson(  # noqa: B008
    request: GenerateLessonRequest,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> GenerateLessonResponse:
  """Generate a lesson from a topic using the two-step pipeline."""
  _validate_generate_request(request, settings)
  
  start = time.monotonic()
  # Resolve per-agent model overrides and provider routing for this request.
  selection = _resolve_model_selection(settings, models=request.models)
  (
    gatherer_provider,
    gatherer_model,
    planner_provider,
    planner_model,
    structurer_provider,
    structurer_model,
    repairer_provider,
    repairer_model,
  ) = selection
  orchestrator = _get_orchestrator(
    settings,
    gatherer_provider=gatherer_provider,
    gatherer_model=gatherer_model,
    planner_provider=planner_provider,
    planner_model=planner_model,
    structurer_provider=structurer_provider,
    structurer_model=structurer_model,
    repair_provider=repairer_provider,
    repair_model=repairer_model,
  )
  language = _resolve_primary_language(request)
  learner_level = _resolve_learner_level(request)
  result = await orchestrator.generate_lesson(
    topic=request.topic,
    details=request.details,
    blueprint=request.blueprint,
    teaching_style=request.teaching_style,
    learner_level=learner_level,
    depth=request.depth,
    schema_version=request.schema_version or settings.schema_version,
    structurer_model=structurer_model,
    gatherer_model=gatherer_model,
    structured_output=True,
    language=language,
    widgets=request.widgets,
  )
  
  lesson_id = generate_lesson_id()
  # lesson_json = lesson_to_shorthand(result.lesson_json)
  latency_ms = int((time.monotonic() - start) * 1000)

  record = LessonRecord(
    lesson_id=lesson_id,
    topic=request.topic,
    title=result.lesson_json["title"],
    created_at=time.strftime(_DATE_FORMAT, time.gmtime()),
    schema_version=request.schema_version or settings.schema_version,
    prompt_version=settings.prompt_version,
    provider_a=result.provider_a,
    model_a=result.model_a,
    provider_b=result.provider_b,
    model_b=result.model_b,
    lesson_json=json.dumps(result.lesson_json, ensure_ascii=True),
    status="ok",
    latency_ms=latency_ms,
    idempotency_key=request.idempotency_key,
  )
  
  repo = _get_repo(settings)
  await run_in_threadpool(repo.create_lesson, record)
  
  return GenerateLessonResponse(
    lesson_id=lesson_id,
    lesson_json=result.lesson_json,
    meta=LessonMeta(
      provider_a=result.provider_a,
      model_a=result.model_a,
      provider_b=result.provider_b,
      model_b=result.model_b,
      latency_ms=latency_ms,
    ),
    logs=result.logs,  # Include logs from orchestrator
  )


async def _create_job_record(
    request: GenerateLessonRequest, settings: Settings
) -> JobCreateResponse:
  _validate_generate_request(request, settings)
  repo = _get_jobs_repo(settings)
  # Precompute section count so the client can render placeholders immediately.
  expected_sections = _expected_sections_from_request(request)

  if request.idempotency_key:
    existing = await run_in_threadpool(repo.find_by_idempotency_key, request.idempotency_key)

    if existing:
      response_expected = existing.expected_sections or expected_sections
      return JobCreateResponse(job_id=existing.job_id, expected_sections=response_expected)
  
  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  request_payload = request.model_dump(mode="python", by_alias=True)
  record = JobRecord(
    job_id=job_id,
    request=request_payload,
    status="queued",
    phase="queued",
    subphase=None,
    expected_sections=expected_sections,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=settings.job_max_retries,
    retry_sections=None,
    retry_agents=None,
    progress=0.0,
    logs=[],
    result_json=None,
    validation=None,
    cost=None,
    created_at=timestamp,
    updated_at=timestamp,
    completed_at=None,
    ttl=_compute_job_ttl(settings),
    idempotency_key=request.idempotency_key,
  )
  await run_in_threadpool(repo.create_job, record)
  return JobCreateResponse(job_id=job_id, expected_sections=expected_sections)


async def _process_job_async(job_id: str, settings: Settings) -> None:
  """Run a queued job in-process to update status as work progresses."""
  
  from app.jobs.worker import JobProcessor
  
  # Fetch the queued record so we can process only if it still exists.
  repo = _get_jobs_repo(settings)
  record = await run_in_threadpool(repo.get_job, job_id)
  
  if record is None:
    return
  
  # Run the job with a fresh processor to update progress states.
  processor = JobProcessor(
    jobs_repo=repo,
    orchestrator=_get_orchestrator(settings),
    settings=settings,
  )
  # Execute the job asynchronously so progress updates stream back to storage.
  await processor.process_job(record)


def _kickoff_job_processing(background_tasks: BackgroundTasks, job_id: str, settings: Settings) -> None:
  """Schedule background processing so clients see status updates."""
  
  # Fire-and-forget processing to keep the API responsive.
  # Skip in-process execution when external workers (Lambda) are responsible.
  
  if not settings.jobs_auto_process:
    return
  
  # Defer to the shared worker loop to avoid duplicate processing.
  
  if _JOB_WORKER_ACTIVE:
    return
  
  # Prefer immediate scheduling on the running loop to start work right away.
  
  try:
    loop = asyncio.get_running_loop()
  
  
  except RuntimeError:
    background_tasks.add_task(_process_job_async, job_id, settings)
    return
  
  task = loop.create_task(_process_job_async(job_id, settings))
  task.add_done_callback(_log_job_task_failure)


def _log_job_task_failure(task: asyncio.Task[None]) -> None:
  """Log unexpected failures from background job tasks."""
  
  try:
    task.result()
  
  
  except Exception as exc:  # noqa: BLE001
    logger.error("Job processing task failed: %s", exc, exc_info=True)


@app.post(
  "/v1/jobs",
  response_model=JobCreateResponse,
  dependencies=[Depends(_require_dev_key)],
)
async def create_job(  # noqa: B008
    request: GenerateLessonRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobCreateResponse:
  """Create a background lesson generation job."""
  response = await _create_job_record(request, settings)
  
  # Kick off processing so the client can poll for status immediately.
  _kickoff_job_processing(background_tasks, response.job_id, settings)
  
  return response


@app.post(
  "/v1/lessons/jobs",
  response_model=JobCreateResponse,
  dependencies=[Depends(_require_dev_key)],
)
async def create_lesson_job(  # noqa: B008
    request: GenerateLessonRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobCreateResponse:
  """Alias route for creating a background lesson generation job."""
  response = await _create_job_record(request, settings)
  
  # Kick off processing so the client can poll for status immediately.
  _kickoff_job_processing(background_tasks, response.job_id, settings)
  
  return response


@app.post(
  "/v1/writing/check",
  response_model=JobCreateResponse,
  status_code=status.HTTP_202_ACCEPTED,
  dependencies=[Depends(_require_dev_key)],
)
async def create_writing_check(  # noqa: B008
    request: WritingCheckRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobCreateResponse:
  """Create a background job to check a writing task response."""
  _validate_writing_request(request)
  repo = _get_jobs_repo(settings)
  job_id = generate_job_id()
  timestamp = time.strftime(_DATE_FORMAT, time.gmtime())
  
  record = JobRecord(
    job_id=job_id,
    request=request.model_dump(mode="python"),
    status="queued",
    phase="queued",
    expected_sections=0,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=settings.job_max_retries,
    retry_sections=None,
    retry_agents=None,
    created_at=timestamp,
    updated_at=timestamp,
    ttl=_compute_job_ttl(settings),
  )
  await run_in_threadpool(repo.create_job, record)
  response = JobCreateResponse(job_id=job_id, expected_sections=0)
  
  # Kick off processing so the client can poll for status immediately.
  _kickoff_job_processing(background_tasks, response.job_id, settings)
  
  return response


@app.get(
  "/v1/jobs/{job_id}",
  response_model=JobStatusResponse,
  dependencies=[Depends(_require_dev_key)],
)
async def get_job_status(  # noqa: B008
    job_id: str,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobStatusResponse:
  """Fetch the status and result of a background job."""
  repo = _get_jobs_repo(settings)
  record = await run_in_threadpool(repo.get_job, job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  return _job_status_from_record(record)


@app.post(
  "/v1/jobs/{job_id}/cancel",
  response_model=JobStatusResponse,
  dependencies=[Depends(_require_dev_key)],
)
async def cancel_job(  # noqa: B008
    job_id: str,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobStatusResponse:
  """Request cancellation of a running background job."""
  repo = _get_jobs_repo(settings)
  record = await run_in_threadpool(repo.get_job, job_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  if record.status in ("done", "error", "canceled"):
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT,
      detail="Job is already finalized and cannot be canceled.",
    )
  updated = await run_in_threadpool(
    repo.update_job,
    job_id,
    status="canceled",
    phase="canceled",
    subphase=None,
    progress=100.0,
    logs=record.logs + ["Job cancellation requested by client."],
    completed_at=time.strftime(_DATE_FORMAT, time.gmtime()),
  )
  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)
  return _job_status_from_record(updated)


@app.post(
  "/v1/jobs/{job_id}/retry",
  response_model=JobStatusResponse,
  dependencies=[Depends(_require_dev_key)],
)
async def retry_job(  # noqa: B008
    job_id: str,
    payload: JobRetryRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobStatusResponse:
  """Retry a failed job with optional section/agent targeting."""
  repo = _get_jobs_repo(settings)
  record = await run_in_threadpool(repo.get_job, job_id)

  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG)

  # Only finalized failures should be eligible for retry.
  if record.status not in ("error", "canceled"):
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT,
      detail="Only failed or canceled jobs can be retried.",
    )

  # Enforce the retry limit to avoid unbounded reprocessing.
  retry_count = record.retry_count or 0
  max_retries = record.max_retries if record.max_retries is not None else settings.job_max_retries

  if retry_count >= max_retries:
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT,
      detail="Retry limit reached for this job.",
    )

  # Resolve expected sections for validation against retry targets.
  try:
    parsed_request = _parse_job_request(record.request)

  except ValidationError as exc:
    raise HTTPException(
      status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
      detail="Stored job request failed validation.",
    ) from exc

  if isinstance(parsed_request, WritingCheckRequest):

    if payload.sections or payload.agents:
      raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Writing check retries do not support section or agent targeting.",
      )
    expected_sections = 0

  else:
    expected_sections = record.expected_sections or _expected_sections_from_request(parsed_request)

  # Normalize retry sections to a unique, ordered list.
  retry_sections = None

  if payload.sections:

    # Ensure retry section indexes are within expected bounds.
    invalid = [index for index in payload.sections if index >= expected_sections]

    if invalid:
      raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Retry section indexes exceed expected section count.",
      )
    retry_sections = sorted(set(payload.sections))

  # Preserve agent order while deduplicating retry targets.
  retry_agents = list(dict.fromkeys(payload.agents)) if payload.agents else None
  logs = record.logs + [
    f"Retry attempt {retry_count + 1} queued.",
  ]
  # Requeue the job with retry metadata so the worker can resume.
  updated = await run_in_threadpool(
    repo.update_job,
    job_id,
    status="queued",
    phase="queued",
    subphase="retry",
    progress=0.0,
    logs=logs,
    retry_count=retry_count + 1,
    max_retries=max_retries,
    retry_sections=retry_sections,
    retry_agents=retry_agents,
    current_section_index=None,
    current_section_status=None,
    current_section_retry_count=None,
    current_section_title=None,
    completed_at=None,
  )

  if updated is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

  # Kick off processing so retries start immediately when auto-processing is enabled.
  _kickoff_job_processing(background_tasks, updated.job_id, settings)
  return _job_status_from_record(updated)


@app.get(
  "/v1/lessons/{lesson_id}",
  response_model=LessonRecordResponse,
  dependencies=[Depends(_require_dev_key)],
)
async def get_lesson(  # noqa: B008
    lesson_id: str,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> LessonRecordResponse:
  """Fetch a stored lesson by identifier, consistent with async job persistence."""
  repo = _get_repo(settings)
  record = await run_in_threadpool(repo.get_lesson, lesson_id)
  if record is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found.")
  
  lesson_json = json.loads(record.lesson_json)
  return LessonRecordResponse(
    lesson_id=record.lesson_id,
    topic=record.topic,
    title=record.title,
    created_at=record.created_at,
    schema_version=record.schema_version,
    prompt_version=record.prompt_version,
    lesson_json=lesson_json,
    meta=LessonMeta(
      provider_a=record.provider_a,
      model_a=record.model_a,
      provider_b=record.provider_b,
      model_b=record.model_b,
      latency_ms=record.latency_ms,
    ),
  )

