from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Awaitable, Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from starlette.concurrency import run_in_threadpool

from app.ai.orchestrator import DgsOrchestrator
from app.config import Settings, get_settings
from app.jobs.guardrails import MAX_ITEM_BYTES, estimate_bytes
from app.jobs.models import JobRecord
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

    def formatException(
        self,
        ei: tuple[type[BaseException] | None, BaseException | None, TracebackType | None],
    ) -> str:  # noqa: N802
        import traceback

        lines = traceback.format_exception(*ei)
        # Keep header + last 5 lines of traceback
        if len(lines) > 6:
            return "".join(lines[:1] + ["    ...\n"] + lines[-5:])
        return "".join(lines)


# Configure Root Logger explicitly (safety against uvicorn hijacking)
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# Stream Handler (Console) - Truncated
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(
    TruncatedFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
)
root_logger.addHandler(stream_handler)

# File Handler
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

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


class LessonConstraints(BaseModel):
    """Optional constraints for lesson generation."""

    learner_level: Literal["Newbie", "Beginner", "Intermediate", "Expert"] | None = Field(
        default=None, alias="learnerLevel"
    )
    language: StrictStr | None = None
    length: Literal["Highlights", "Detailed", "Training"] | None = None
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class GenerateLessonRequest(BaseModel):
    """Request payload for lesson generation."""

    topic: StrictStr = Field(min_length=1)
    topic_details: StrictStr | None = None
    constraints: LessonConstraints | None = None
    schema_version: StrictStr | None = None
    idempotency_key: StrictStr | None = None
    mode: Literal["fast", "balanced", "best"] | None = Field(default="balanced")
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


class JobCreateResponse(BaseModel):
    """Response payload for job creation."""

    job_id: StrictStr = Field(serialization_alias="jobId", validation_alias="jobId")
    model_config = ConfigDict(populate_by_name=True)


MAX_REQUEST_BYTES = MAX_ITEM_BYTES // 2


def _get_orchestrator(settings: Settings) -> DgsOrchestrator:
    return DgsOrchestrator(
        gatherer_provider=settings.gatherer_provider,
        gatherer_model=settings.gatherer_model,
        structurer_provider=settings.structurer_provider,
        structurer_model=settings.structurer_model,
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


def _resolve_structurer_model(settings: Settings, mode: str | None) -> str | None:
    if mode == "fast":
        return settings.structurer_model_fast or settings.structurer_model
    if mode == "best":
        return settings.structurer_model_best or settings.structurer_model
    return settings.structurer_model_balanced or settings.structurer_model


def _require_dev_key(  # noqa: B008
    x_dgs_dev_key: str = Header(..., alias="X-DGS-Dev-Key"),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> None:
    if x_dgs_dev_key != settings.dev_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev key.")


def _validate_generate_request(request: GenerateLessonRequest, settings: Settings) -> None:
    """Enforce topic length and persistence size constraints."""
    if len(request.topic) > settings.max_topic_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Topic exceeds max length of {settings.max_topic_length}.",
        )
    if estimate_bytes(request.model_dump(mode="python", by_alias=True)) > MAX_REQUEST_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request payload is too large for persistence.",
        )


def _compute_job_ttl(settings: Settings) -> int | None:
    if settings.jobs_ttl_seconds is None:
        return None
    return int(time.time()) + settings.jobs_ttl_seconds


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/lessons/validate",
    response_model=ValidationResponse,
    dependencies=[Depends(_require_dev_key)],
)
async def validate_endpoint(payload: dict[str, Any]) -> ValidationResponse:
    """Validate a lesson payload against schema + widget registry."""

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
    orchestrator = _get_orchestrator(settings)
    result = await orchestrator.generate_lesson(
        topic=request.topic,
        topic_details=request.topic_details,
        constraints=request.constraints.model_dump(by_alias=True) if request.constraints else None,
        schema_version=request.schema_version or settings.schema_version,
        structurer_model=_resolve_structurer_model(settings, request.mode),
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


@app.get(
    "/v1/lessons/{lesson_id}",
    response_model=LessonRecordResponse,
    dependencies=[Depends(_require_dev_key)],
)
async def get_lesson(  # noqa: B008
    lesson_id: str,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> LessonRecordResponse:
    """Fetch a stored lesson by identifier."""
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
