import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.core.logging import _initialize_logging
from app.services.model_routing import _get_orchestrator
from app.storage.factory import _get_jobs_repo

# Track background job worker state for lifecycle management.
_JOB_WORKER_TASK: asyncio.Task[None] | None = None
_JOB_WORKER_ACTIVE = False


def _log_job_task_failure(task: asyncio.Task[None]) -> None:
    """Log unexpected failures from background job tasks."""
    logger = logging.getLogger("app.core.lifespan")
    try:
        task.result()

    except Exception as exc:  # noqa: BLE001
        logger.error("Job processing task failed: %s", exc, exc_info=True)


async def _job_worker_loop(active_settings: Settings) -> None:
    """Poll for queued jobs so processing happens even if kickoff is missed."""
    from app.jobs.worker import JobProcessor

    logger = logging.getLogger("app.core.lifespan")

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


def _start_job_worker(active_settings: Settings) -> None:
    """Start a lightweight job poller to ensure queued jobs are processed."""
    global _JOB_WORKER_TASK, _JOB_WORKER_ACTIVE
    logger = logging.getLogger("app.core.lifespan")

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
    logger = logging.getLogger("app.core.lifespan")

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ensure logging is correctly set up after uvicorn starts."""
    from app.config import get_settings

    settings = get_settings()
    logger = logging.getLogger("app.core.lifespan")

    try:
        _initialize_logging(settings)
        logger.info("Startup complete - logging verified.")

        _start_job_worker(settings)

    except Exception:
        logger.warning(
            "Initial logging setup failed; will retry on lifespan.", exc_info=True
        )

    yield

    _stop_job_worker()
