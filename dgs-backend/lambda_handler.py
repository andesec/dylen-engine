import asyncio
from typing import Any

from mangum import Mangum

from app.config import get_settings
from app.jobs.worker import JobProcessor
from app.main import _get_jobs_repo, _get_orchestrator, app

handler = Mangum(app)


def process_jobs_handler(
    _event: dict[str, Any] | None = None, _context: Any | None = None
) -> dict[str, Any]:
    """Lambda entrypoint for queued job processing."""

    async def _process() -> dict[str, Any]:
        settings = get_settings()
        processor = JobProcessor(
            jobs_repo=_get_jobs_repo(settings),
            orchestrator=_get_orchestrator(settings),
            settings=settings,
        )
        processed = await processor.process_queue()
        return {"processedJobIds": [job.job_id for job in processed]}

    return asyncio.run(_process())
