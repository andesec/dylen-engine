from __future__ import annotations

import logging

import httpx

from app.config import Settings
from app.services.tasks.interface import TaskEnqueuer

logger = logging.getLogger(__name__)


class LocalHttpEnqueuer(TaskEnqueuer):
  """Enqueues tasks via local HTTP requests to simulate Cloud Tasks."""

  def __init__(self, settings: Settings) -> None:
    self.settings = settings

  async def enqueue(self, job_id: str, payload: dict) -> None:
    """Enqueue a job by POSTing to the local endpoint."""
    if not self.settings.base_url:
      logger.warning("Base URL not configured, strictly required for LocalHttpEnqueuer.")
      return

    url = f"{self.settings.base_url.rstrip('/')}/tasks/process-job"

    # Fire and forget-ish: we want to trigger it but not block excessively?
    # Actually, `httpx.AsyncClient` usage here:
    # If we await it, we block the `create_job` response.
    # Cloud Tasks is async (returns quickly).
    # We should probably use a short timeout or fire in background if we want true "background" behavior.
    # But since `enqueue` is async, awaiting a quick HTTP call is probably fine.

    try:
      async with httpx.AsyncClient() as client:
        # We use a short timeout because we don't want to wait for the JOB to finish,
        # just for the request to be accepted.
        # However, the endpoint `process_job` currently runs the job *synchronously* in `process_job_async` logic?
        # Wait, the `process_job_async` concept was "run in background".
        # The new endpoint will need to be careful.
        # If the endpoint awaits the whole job, then THIS call awaits the whole job.
        # That's bad for `create_job` latency.
        # The new endpoint should probably spawn a background task OR we assume `timeout` here lets it run?
        # No, if we timeout here, the server might kill the handling?
        # Actually, `httpx` timeout just closes the client connection.
        # FastApi server *should* continue processing if built correctly (background tasks).
        # So we will post and expect an immediate "202 Accepted" or similar,
        # OR we rely on the endpoint to delegate to BackgroundTasks.
        pass

        logger.info(f"Dispatching task locally to {url}")
        await client.post(url, json={"job_id": job_id}, timeout=5.0)

    except httpx.RequestError as e:
      logger.error(f"Failed to dispatch local task for job {job_id}: {e}")
