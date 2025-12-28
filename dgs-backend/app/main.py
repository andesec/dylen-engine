from __future__ import annotations

import json
import time
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
from starlette.concurrency import run_in_threadpool

from app.ai.orchestrator import DgsOrchestrator
from app.config import Settings, get_settings
from app.schema.serialize_lesson import lesson_to_shorthand
from app.schema.validate_lesson import validate_lesson
from app.storage.dynamodb_repo import DynamoLessonsRepository
from app.storage.lessons_repo import LessonRecord, LessonsRepository
from app.utils.ids import generate_lesson_id

app = FastAPI()


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


def _get_orchestrator(settings: Settings) -> DgsOrchestrator:
    return DgsOrchestrator(
        gatherer_provider=settings.gatherer_provider,
        gatherer_model=settings.gatherer_model,
        structurer_provider=settings.structurer_provider,
        structurer_model=settings.structurer_model,
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


def _resolve_structurer_model(settings: Settings, mode: str | None) -> str | None:
    if mode == "fast":
        return settings.structurer_model_fast or settings.structurer_model
    if mode == "best":
        return settings.structurer_model_best or settings.structurer_model
    return settings.structurer_model_balanced or settings.structurer_model


def _require_dev_key(
    x_dgs_dev_key: str = Header(..., alias="X-DGS-Dev-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    if x_dgs_dev_key != settings.dev_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid dev key.")


@app.on_event("startup")
async def _configure_cors() -> None:
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["content-type", "authorization", "x-dgs-dev-key"],
        expose_headers=["content-length"],
    )


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
async def generate_lesson(
    request: GenerateLessonRequest,
    settings: Settings = Depends(get_settings),
) -> GenerateLessonResponse:
    """Generate a lesson from a topic using the two-step pipeline."""
    if len(request.topic) > settings.max_topic_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Topic exceeds max length of {settings.max_topic_length}.",
        )

    start = time.monotonic()
    orchestrator = _get_orchestrator(settings)
    result = await orchestrator.generate_lesson(
        topic=request.topic,
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
    )


@app.get(
    "/v1/lessons/{lesson_id}",
    response_model=LessonRecordResponse,
    dependencies=[Depends(_require_dev_key)],
)
async def get_lesson(
    lesson_id: str,
    settings: Settings = Depends(get_settings),
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

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
