from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
)
from starlette.concurrency import run_in_threadpool

from app.ai.orchestrator import DgsOrchestrator
from app.config import Settings, get_settings
from app.jobs.guardrails import MAX_ITEM_BYTES, estimate_bytes
from app.jobs.models import JobRecord, JobStatus
from app.schema.serialize_lesson import lesson_to_shorthand
from app.schema.validate_lesson import validate_lesson
from app.storage.dynamodb_jobs_repo import DynamoJobsRepository
from app.storage.dynamodb_repo import DynamoLessonsRepository
from app.storage.lessons_repo import LessonRecord, LessonsRepository
from app.utils.ids import generate_job_id, generate_lesson_id

settings = get_settings()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["content-type", "authorization", "x-dgs-dev-key"],
    expose_headers=["content-length"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler to catch unhandled errors."""
    logger = logging.getLogger("uvicorn.error")
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal Server Error", "error": str(exc)},
    )


# Create logs directory if it doesn't exist
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# Generate log filename with timestamp
log_file = log_dir / f"dgs_app_{time.strftime('%Y%m%d_%H%M%S')}.log"

# Define formatter
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"
)


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


# Configure Root Logger explicitly (safety against uvicorn hijacking)
root_logger = logging.getLogger()
# Stream Handler (Console) - Truncated
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(
    TruncatedFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
)

# File Handler
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(formatter)

def setup_logging():
    """Ensure all loggers use our handlers and propagate to root."""
    # Capture uvicorn loggers
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        l = logging.getLogger(logger_name)
        l.handlers = [stream_handler, file_handler]
        l.propagate = False

    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[stream_handler, file_handler],
        force=True,
    )
    # Re-apply to root just in case
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    if not root.handlers:
        root.addHandler(stream_handler)
        root.addHandler(file_handler)

setup_logging()

# Silence noisy libraries
logging.getLogger("botocore").setLevel(logging.ERROR)
logging.getLogger("boto3").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)

logger = logging.getLogger("app.main")
logger.info(f"Logging initialized. Writing to {log_file}")


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


class ValidationLevel(str, Enum):
    """Supported validation strictness levels."""

    BASIC = "basic"
    STRICT = "strict"


class GenerationModel(str, Enum):
    """Supported model identifiers exposed to clients."""

    GEMINI_25_PRO = "gemini-2.5-pro"
    GEMINI_25_FLASH = "gemini-2.5-flash"
    GEMINI_20_FLASH = "gemini-2.0-flash"
    GEMINI_20_FLASH_EXP = "gemini-2.0-flash-exp"
    GEMINI_PRO_LATEST = "gemini-pro-latest"
    GEMINI_FLASH_LATEST = "gemini-flash-latest"
    GPT4O_MINI = "openai/gpt-4o-mini"
    GPT4O = "openai/gpt-4o"
    CLAUDE_35_SONNET = "anthropic/claude-3.5-sonnet"
    GEMINI_FLASH_FREE = "google/gemini-2.0-flash-exp:free"


class GenerationConstraints(BaseModel):
    """Specific constraints for lesson content generation."""

    primaryLanguage: str | None = Field(default=None, alias="primaryLanguage")
    learnerLevel: str | None = Field(default=None, alias="learnerLevel")
    length: Literal["Highlights", "Detailed", "Training"] | None = Field(
        default=None, alias="length"
    )
    sections: StrictInt | None = Field(default=None, ge=1, le=10, alias="sections")

    model_config = ConfigDict(populate_by_name=True)


class GenerationConfig(BaseModel):
    """Tunable configuration for lesson generation."""

    model: GenerationModel = Field(
        default=GenerationModel.GPT4O_MINI,
        description="Model used for lesson structuring.",
    )
    temperature: StrictFloat = Field(
        default=0.4,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for the generation pipeline.",
    )
    max_output_tokens: StrictInt = Field(
        default=4096,
        ge=256,
        le=65536,
        description="Upper bound on tokens produced during structured generation.",
    )
    validation_level: ValidationLevel = Field(
        default=ValidationLevel.STRICT,
        description="Level of validation applied to the generated lesson.",
    )
    structured_output: bool = Field(
        default=True,
        description="If false, fall back to raw JSON generation instead of structured mode.",
    )
    language: StrictStr = Field(
        default="en",
        min_length=2,
        max_length=8,
        description="Preferred language for the resulting lesson content.",
    )
    model_config = ConfigDict(extra="forbid")


class GenerateLessonRequest(BaseModel):
    """Request payload for lesson generation."""

    topic: StrictStr = Field(min_length=1, description="Topic to generate a lesson for.")
    prompt: StrictStr = Field(
        min_length=1,
        description="User-supplied guidance (max 250 words).",
    )
    config: GenerationConfig = Field(
        default_factory=GenerationConfig, description="Configurable generation parameters."
    )
    schema_version: StrictStr | None = Field(
        default=None, description="Optional schema version to pin the lesson output to."
    )
    idempotency_key: StrictStr | None = Field(
        default=None,
        description="Idempotency key to prevent duplicate lesson generation.",
        alias="idempotency_key",
    )
    constraints: GenerationConstraints | None = Field(
        default=None, description="Domain-specific generation constraints."
    )
    model_config = ConfigDict(extra="forbid")


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


class WritingCheckRequest(BaseModel):
    """Request payload for response evaluation."""

    text: StrictStr = Field(min_length=1, description="The user-written response to check (max 300 words).")
    criteria: dict[str, Any] = Field(description="The evaluation criteria from the lesson.")
    model_config = ConfigDict(extra="forbid")


class JobCreateResponse(BaseModel):
    """Response payload for job creation."""

    job_id: StrictStr = Field(serialization_alias="jobId", validation_alias="jobId")
    model_config = ConfigDict(populate_by_name=True)


class JobStatusResponse(BaseModel):
    """Status payload for an asynchronous lesson generation job."""

    job_id: StrictStr = Field(serialization_alias="jobId", validation_alias="jobId")
    status: JobStatus
    phase: StrictStr | None = None
    subphase: StrictStr | None = None
    progress: StrictFloat | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Normalized progress indicator when available.",
    )
    logs: list[StrictStr] = Field(default_factory=list)
    request: GenerateLessonRequest
    result: dict[str, Any] | None = None
    validation: ValidationResponse | None = None
    cost: dict[str, Any] | None = None
    created_at: StrictStr = Field(serialization_alias="createdAt", validation_alias="createdAt")
    updated_at: StrictStr = Field(serialization_alias="updatedAt", validation_alias="updatedAt")
    completed_at: StrictStr | None = Field(
        default=None, serialization_alias="completedAt", validation_alias="completedAt"
    )
    model_config = ConfigDict(populate_by_name=True)


MAX_REQUEST_BYTES = MAX_ITEM_BYTES // 2


def _get_orchestrator(
    settings: Settings,
    *,
    gatherer_provider: str | None = None,
    gatherer_model: str | None = None,
    structurer_provider: str | None = None,
    structurer_model: str | None = None,
) -> DgsOrchestrator:
    return DgsOrchestrator(
        gatherer_provider=gatherer_provider or settings.gatherer_provider,
        gatherer_model=gatherer_model or settings.gatherer_model,
        structurer_provider=structurer_provider or settings.structurer_provider,
        structurer_model=structurer_model or settings.structurer_model,
        repair_provider=settings.repair_provider,
        repair_model=settings.repair_model,
        schema_version=settings.schema_version,
    )


def _get_repo(settings: Settings) -> LessonsRepository:
    return DynamoLessonsRepository(
        table_name=settings.ddb_table,
        region=settings.ddb_region,
        endpoint_url=settings.ddb_endpoint_url,
        tenant_key=settings.tenant_key,
        lesson_id_index=settings.lesson_id_index_name,
    )


def _get_jobs_repo(settings: Settings) -> DynamoJobsRepository:
    return DynamoJobsRepository(
        table_name=settings.jobs_table,
        region=settings.ddb_region,
        endpoint_url=settings.ddb_endpoint_url,
        all_jobs_index=settings.jobs_all_jobs_index_name,
        idempotency_index=settings.jobs_idempotency_index_name,
    )


_GEMINI_STRUCTURER_MODELS = {
    GenerationModel.GEMINI_20_FLASH_EXP,
    GenerationModel.GEMINI_20_FLASH,
    GenerationModel.GEMINI_25_FLASH,
    GenerationModel.GEMINI_25_PRO,
    GenerationModel.GEMINI_FLASH_LATEST,
    GenerationModel.GEMINI_PRO_LATEST,
}

_OPENROUTER_STRUCTURER_MODELS = {
    GenerationModel.GPT4O_MINI,
    GenerationModel.GPT4O,
    GenerationModel.CLAUDE_35_SONNET,
    GenerationModel.GEMINI_FLASH_FREE,
}


def _resolve_structurer_selection(
    settings: Settings, config: GenerationConfig | None
) -> tuple[str, str | None]:
    """
    Derive the structurer provider + model based on the user config.

    Falls back to environment defaults when no config is provided.
    """
    if config is None:
        return settings.structurer_provider, settings.structurer_model

    if config.model in _GEMINI_STRUCTURER_MODELS:
        return "gemini", config.model.value
    if config.model in _OPENROUTER_STRUCTURER_MODELS:
        return "openrouter", config.model.value
    # Default to settings if we cannot infer a provider
    return settings.structurer_provider, config.model.value


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
    """Enforce topic/prompt length and persistence size constraints."""
    if len(request.topic) > settings.max_topic_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Topic exceeds max length of {settings.max_topic_length} chars.",
        )
    if request.prompt:
        word_count = _count_words(request.prompt)
        if word_count > 250:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User prompt is too long ({word_count} words). Max 250 words.",
            )
    if estimate_bytes(request.model_dump(mode="python", by_alias=True)) > MAX_REQUEST_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request payload is too large for persistence.",
        )
    
    # Model validation ...
    if request.config and request.config.model:
        model_val = request.config.model
        if not any(model_val in group for group in (_GEMINI_STRUCTURER_MODELS, _OPENROUTER_STRUCTURER_MODELS)):
            # If not in our enum, it might be a raw string if we allow it, 
            # but if it's an enum we already validated at Pydantic level.
            pass

    constraints = (
        request.constraints.model_dump(mode="python", by_alias=True) if request.constraints else {}
    )
    try:
        from app.jobs.progress import build_call_plan  # Local import to avoid circular deps

        build_call_plan({"constraints": constraints})
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


def _build_constraints(
    config: GenerationConfig | None, constraints: GenerationConstraints | None = None
) -> dict[str, Any] | None:
    """Translate user config into orchestration constraints."""
    out: dict[str, Any] = {}
    if config and config.language:
        out["language"] = config.language

    if constraints:
        out.update(constraints.model_dump(mode="python", by_alias=True, exclude_none=True))

    return out or None


def _compute_job_ttl(settings: Settings) -> int | None:
    if settings.jobs_ttl_seconds is None:
        return None
    return int(time.time()) + settings.jobs_ttl_seconds


def _job_status_from_record(record: JobRecord) -> JobStatusResponse:
    """Convert a persisted job record into an API response payload."""
    try:
        request = GenerateLessonRequest.model_validate(record.request)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored job request failed validation.",
        ) from exc

    validation = None
    if record.validation is not None:
        validation = ValidationResponse.model_validate(record.validation)

    return JobStatusResponse(
        job_id=record.job_id,
        status=record.status,
        phase=record.phase,
        subphase=record.subphase,
        progress=record.progress,
        logs=record.logs or [],
        request=request,
        result=record.result_json,
        validation=validation,
        cost=record.cost,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


@app.on_event("startup")
async def startup_event():
    """Ensure logging is correctly set up after uvicorn starts."""
    setup_logging()
    logger.info("Startup complete - logging verified.")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
    dependencies=[Depends(_require_dev_key)],
)
async def generate_lesson(  # noqa: B008
    request: GenerateLessonRequest,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> GenerateLessonResponse:
    """Generate a lesson from a topic using the two-step pipeline."""
    _validate_generate_request(request, settings)

    start = time.monotonic()
    structurer_provider, structurer_model = _resolve_structurer_selection(settings, request.config)
    orchestrator = _get_orchestrator(
        settings,
        structurer_provider=structurer_provider,
        structurer_model=structurer_model,
    )
    constraints = _build_constraints(request.config, request.constraints)
    result = await orchestrator.generate_lesson(
        topic=request.topic,
        prompt=request.prompt,
        constraints=constraints,
        schema_version=request.schema_version or settings.schema_version,
        structurer_model=structurer_model,
        structured_output=request.config.structured_output,
        language=request.config.language,
    )

    ok, errors, lesson_model = validate_lesson(result.lesson_json)
    if not ok or lesson_model is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=errors)
    if request.schema_version and lesson_model.version != request.schema_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Schema version mismatch: {lesson_model.version}",
        )

    lesson_id = generate_lesson_id()
    lesson_json = lesson_to_shorthand(lesson_model)
    latency_ms = int((time.monotonic() - start) * 1000)

    record = LessonRecord(
        lesson_id=lesson_id,
        topic=request.topic,
        title=lesson_model.title,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        schema_version=request.schema_version or settings.schema_version,
        prompt_version=settings.prompt_version,
        provider_a=result.provider_a,
        model_a=result.model_a,
        provider_b=result.provider_b,
        model_b=result.model_b,
        lesson_json=json.dumps(lesson_json, ensure_ascii=True),
        status="ok",
        latency_ms=latency_ms,
        idempotency_key=request.idempotency_key,
    )

    repo = _get_repo(settings)
    await run_in_threadpool(repo.create_lesson, record)

    return GenerateLessonResponse(
        lesson_id=lesson_id,
        lesson_json=lesson_json,
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
    if request.idempotency_key:
        existing = await run_in_threadpool(repo.find_by_idempotency_key, request.idempotency_key)
        if existing:
            return JobCreateResponse(job_id=existing.job_id)

    job_id = generate_job_id()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    request_payload = request.model_dump(mode="python", by_alias=True)
    record = JobRecord(
        job_id=job_id,
        request=request_payload,
        status="queued",
        phase="queued",
        subphase=None,
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
    return JobCreateResponse(job_id=job_id)


@app.post(
    "/v1/jobs",
    response_model=JobCreateResponse,
    dependencies=[Depends(_require_dev_key)],
)
async def create_job(  # noqa: B008
    request: GenerateLessonRequest,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobCreateResponse:
    """Create a background lesson generation job."""
    return await _create_job_record(request, settings)


@app.post(
    "/v1/lessons/jobs",
    response_model=JobCreateResponse,
    dependencies=[Depends(_require_dev_key)],
)
async def create_lesson_job(  # noqa: B008
    request: GenerateLessonRequest,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobCreateResponse:
    """Alias route for creating a background lesson generation job."""
    return await _create_job_record(request, settings)


@app.post(
    "/v1/writing/check",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_require_dev_key)],
)
async def create_writing_check(  # noqa: B008
    request: WritingCheckRequest,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobCreateResponse:
    """Create a background job to check a writing task response."""
    _validate_writing_request(request)
    repo = _get_jobs_repo(settings)
    job_id = generate_job_id()
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    record = JobRecord(
        job_id=job_id,
        request=request.model_dump(mode="python"),
        status="queued",
        phase="queued",
        created_at=timestamp,
        updated_at=timestamp,
        ttl=_compute_job_ttl(settings),
    )
    await run_in_threadpool(repo.create_job, record)
    return JobCreateResponse(job_id=job_id)


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
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
        progress=1.0,
        logs=record.logs + ["Job cancellation requested by client."],
        completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
