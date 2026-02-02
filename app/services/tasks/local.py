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

    url = f"{self.settings.base_url.rstrip('/')}/internal/tasks/process-job"
    # Attach the shared secret when configured so internal task dispatch is authorized.
    headers = {}
    if self.settings.task_secret:
      headers["authorization"] = f"Bearer {self.settings.task_secret}"

    # Fire and forget-ish: we want to trigger it but not block excessively?
    # Actually, `httpx.AsyncClient` usage here:
    # If we await it, we block the `create_job` response.
    # Cloud Tasks is async (returns quickly).
    # We should probably use a short timeout or fire in background if we want true "background" behavior.
    # But since `enqueue` is async, awaiting a quick HTTP call is probably fine.

    try:
      async with httpx.AsyncClient() as client:
        logger.info(f"Dispatching task locally to {url}")
        # Use a short timeout because we only need the task to be accepted, not fully processed.
        await client.post(url, json={"job_id": job_id}, headers=headers, timeout=5.0)

    except httpx.RequestError as e:
      logger.error(f"Failed to dispatch local task for job {job_id}: {e}")
