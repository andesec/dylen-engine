from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from app.config import Settings
from app.services.tasks.interface import TaskEnqueuer

logger = logging.getLogger(__name__)


class LocalHttpEnqueuer(TaskEnqueuer):
  """Enqueues tasks via local HTTP requests to simulate Cloud Tasks."""

  def __init__(self, settings: Settings) -> None:
    self.settings = settings

  def _should_use_asgi_transport(self, base_url: str) -> bool:
    """Decide if we should route requests in-process via ASGITransport."""
    # Avoid network/proxy edge-cases for local development by calling the app in-process when possible.
    parsed = urlparse(base_url)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

  def _build_client(self, base_url: str) -> httpx.AsyncClient:
    """Build an httpx client for local task dispatch."""
    # Never trust environment proxy variables for internal task dispatch.
    if self._should_use_asgi_transport(base_url):
      from app.main import app

      transport = httpx.ASGITransport(app=app)
      return httpx.AsyncClient(transport=transport, base_url=base_url, trust_env=False)
    return httpx.AsyncClient(trust_env=False)

  def _task_headers(self) -> dict[str, str]:
    """Build task authentication headers for internal endpoints."""
    # Enforce shared-secret auth for internal endpoints (deny-by-default).
    if not self.settings.task_secret:
      raise RuntimeError("Task secret not configured.")
    return {"authorization": f"Bearer {self.settings.task_secret}"}

  async def enqueue(self, job_id: str, payload: dict) -> None:
    """Enqueue a job by POSTing to the local endpoint."""
    if not self.settings.base_url:
      raise RuntimeError("Base URL not configured, strictly required for LocalHttpEnqueuer.")

    url = f"{self.settings.base_url.rstrip('/')}/internal/tasks/process-job"

    try:
      async with self._build_client(self.settings.base_url) as client:
        # The local task endpoint runs work synchronously, so allow a long deadline for parity with Cloud Tasks.
        logger.info(f"Dispatching task locally to {url}")
        response = await client.post(url, json={"job_id": job_id}, headers=self._task_headers(), timeout=1800.0)
        response.raise_for_status()

    except httpx.HTTPStatusError as e:
      logger.error(f"Local task dispatch returned {e.response.status_code} for job {job_id}: {e.response.text}")
      raise
    except httpx.RequestError as e:
      logger.error(f"Failed to dispatch local task for job {job_id}: {e}")
      raise

  async def enqueue_lesson(self, lesson_id: str, job_id: str, params: dict, user_id: str) -> None:
    """Enqueue a lesson generation task locally."""
    if not self.settings.base_url:
      raise RuntimeError("Base URL not configured, strictly required for LocalHttpEnqueuer.")

    url = f"{self.settings.base_url.rstrip('/')}/worker/process-lesson"

    payload = {"lesson_id": lesson_id, "job_id": job_id, "params": params, "user_id": user_id}

    try:
      async with self._build_client(self.settings.base_url) as client:
        logger.info(f"Dispatching lesson task locally to {url}")
        response = await client.post(url, json=payload, headers=self._task_headers(), timeout=1800.0)
        response.raise_for_status()

    except httpx.HTTPStatusError as e:
      logger.error(f"Local lesson task dispatch returned {e.response.status_code} for lesson {lesson_id}: {e.response.text}")
      raise
    except httpx.RequestError as e:
      logger.error(f"Failed to dispatch local lesson task for lesson {lesson_id}: {e}")
      raise
