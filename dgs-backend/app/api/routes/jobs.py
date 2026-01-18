import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.deps import require_dev_key
from app.api.models import (
    CurrentSectionStatus,
    GenerateLessonRequest,
    JobCreateResponse,
    JobRetryRequest,
    JobStatusResponse,
    ValidationResponse,
    WritingCheckRequest,
)
from app.config import Settings, get_settings
from app.core.lifespan import _JOB_WORKER_ACTIVE
from app.jobs.models import JobRecord
from app.services.model_routing import _get_orchestrator
from app.services.request_validation import (
    _validate_generate_request,
)
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id

router = APIRouter()
logger = logging.getLogger("app.api.routes.jobs")

_JOB_NOT_FOUND_MSG = "Job not found."
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _compute_job_ttl(settings: Settings) -> int | None:
    if settings.jobs_ttl_seconds is None:
        return None
    return int(time.time()) + settings.jobs_ttl_seconds


def _expected_sections_from_request(
    request: GenerateLessonRequest, settings: Settings
) -> int:
    """Compute the expected section count for a lesson job."""
    # Reuse the call plan depth so expected section counts match worker planning.
    from app.jobs.progress import build_call_plan

    plan = build_call_plan(
        request.model_dump(mode="python", by_alias=True),
        merge_gatherer_structurer=settings.merge_gatherer_structurer,
    )
    return plan.depth


def _parse_job_request(
    payload: dict[str, Any],
) -> GenerateLessonRequest | WritingCheckRequest:
    """Resolve the stored job request to the correct request model."""

    # Writing checks carry a distinct payload shape (text + criteria).

    if "text" in payload and "criteria" in payload:
        return WritingCheckRequest.model_validate(payload)

    # Drop deprecated fields so legacy records can still be parsed.
    if "mode" in payload:
        payload = {key: value for key, value in payload.items() if key != "mode"}

    return GenerateLessonRequest.model_validate(payload)


def _job_status_from_record(
    record: JobRecord, settings: Settings
) -> JobStatusResponse:
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
        expected_sections = _expected_sections_from_request(request, settings)

    if expected_sections is None and isinstance(request, WritingCheckRequest):
        expected_sections = 0

    current_section = None

    if (
        record.current_section_index is not None
        and record.current_section_status is not None
    ):
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


async def create_job_record(
    request: GenerateLessonRequest, settings: Settings
) -> JobCreateResponse:
    _validate_generate_request(request, settings)
    repo = _get_jobs_repo(settings)
    # Precompute section count so the client can render placeholders immediately.
    expected_sections = _expected_sections_from_request(request, settings)

    if request.idempotency_key:
        existing = await run_in_threadpool(
            repo.find_by_idempotency_key, request.idempotency_key
        )

        if existing:
            response_expected = existing.expected_sections or expected_sections
            return JobCreateResponse(
                job_id=existing.job_id, expected_sections=response_expected
            )

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


def _log_job_task_failure(task: asyncio.Task[None]) -> None:
    """Log unexpected failures from background job tasks."""

    try:
        task.result()

    except Exception as exc:  # noqa: BLE001
        logger.error("Job processing task failed: %s", exc, exc_info=True)


def kickoff_job_processing(
    background_tasks: BackgroundTasks, job_id: str, settings: Settings
) -> None:
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


@router.post(
    "", response_model=JobCreateResponse, dependencies=[Depends(require_dev_key)]
)
async def create_job(  # noqa: B008
    request: GenerateLessonRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobCreateResponse:
    """Create a background lesson generation job."""
    response = await create_job_record(request, settings)

    # Kick off processing so the client can poll for status immediately.
    kickoff_job_processing(background_tasks, response.job_id, settings)

    return response


@router.post(
    "/{job_id}/retry",
    response_model=JobStatusResponse,
    dependencies=[Depends(require_dev_key)],
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG
        )

    # Only finalized failures should be eligible for retry.
    if record.status not in ("error", "canceled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only failed or canceled jobs can be retried.",
        )

    # Enforce the retry limit to avoid unbounded reprocessing.
    retry_count = record.retry_count or 0
    max_retries = (
        record.max_retries
        if record.max_retries is not None
        else settings.job_max_retries
    )

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
        expected_sections = record.expected_sections or _expected_sections_from_request(
            parsed_request, settings
        )

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
    logs = record.logs + [f"Retry attempt {retry_count + 1} queued."]
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
    kickoff_job_processing(background_tasks, updated.job_id, settings)
    return _job_status_from_record(updated, settings)


@router.post(
    "/{job_id}/cancel",
    response_model=JobStatusResponse,
    dependencies=[Depends(require_dev_key)],
)
async def cancel_job(  # noqa: B008
    job_id: str,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobStatusResponse:
    """Request cancellation of a running background job."""
    repo = _get_jobs_repo(settings)
    record = await run_in_threadpool(repo.get_job, job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG
        )
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG
        )
    return _job_status_from_record(updated, settings)


@router.get(
    "/{job_id}", response_model=JobStatusResponse, dependencies=[Depends(require_dev_key)]
)
async def get_job_status(  # noqa: B008
    job_id: str,
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> JobStatusResponse:
    """Fetch the status and result of a background job."""
    repo = _get_jobs_repo(settings)
    record = await run_in_threadpool(repo.get_job, job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=_JOB_NOT_FOUND_MSG
        )
    return _job_status_from_record(record, settings)
