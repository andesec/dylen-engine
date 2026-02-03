from __future__ import annotations

import json
import logging

from app.config import Settings
from app.services.tasks.interface import TaskEnqueuer
from google.cloud import tasks_v2

logger = logging.getLogger(__name__)


class CloudTasksEnqueuer(TaskEnqueuer):
  """Enqueues tasks to Google Cloud Tasks."""

  def __init__(self, settings: Settings) -> None:
    self.settings = settings
    self.client = tasks_v2.CloudTasksClient()

  async def enqueue(self, job_id: str, payload: dict) -> None:
    """Enqueue a job to Cloud Tasks."""
    if not self.settings.cloud_tasks_queue_path:
      raise RuntimeError("Cloud Tasks queue path not configured.")

    if not self.settings.base_url:
      raise RuntimeError("Base URL not configured.")

    # Enforce shared-secret auth for internal task endpoints (deny-by-default).
    if not self.settings.task_secret:
      raise RuntimeError("Task secret not configured.")

    url = f"{self.settings.base_url}/internal/tasks/process-job"
    headers = {"Content-Type": "application/json"}
    headers["authorization"] = f"Bearer {self.settings.task_secret}"

    http_request: dict[str, object] = {"http_method": tasks_v2.HttpMethod.POST, "url": url, "headers": headers, "body": json.dumps({"job_id": job_id}).encode()}
    if self.settings.cloud_run_invoker_service_account:
      http_request["oidc_token"] = {"service_account_email": self.settings.cloud_run_invoker_service_account}

    task = {"http_request": http_request}

    parent = self.settings.cloud_tasks_queue_path

    try:
      response = self.client.create_task(request={"parent": parent, "task": task})
      logger.info(f"Enqueued task {response.name} for job {job_id}")
    except Exception as e:
      logger.error(f"Failed to enqueue task for job {job_id}: {e}", exc_info=True)
      raise

  async def enqueue_lesson(self, lesson_id: str, job_id: str, params: dict, user_id: str) -> None:
    """Enqueue a lesson generation task to Cloud Tasks."""
    if not self.settings.cloud_tasks_queue_path:
      raise RuntimeError("Cloud Tasks queue path not configured.")

    if not self.settings.base_url:
      raise RuntimeError("Base URL not configured.")

    # Enforce shared-secret auth for internal task endpoints (deny-by-default).
    if not self.settings.task_secret:
      raise RuntimeError("Task secret not configured.")

    url = f"{self.settings.base_url}/worker/process-lesson"

    payload = {"lesson_id": lesson_id, "job_id": job_id, "params": params, "user_id": user_id}

    headers = {"Content-Type": "application/json"}
    headers["authorization"] = f"Bearer {self.settings.task_secret}"

    task = {"http_request": {"http_method": tasks_v2.HttpMethod.POST, "url": url, "headers": headers, "body": json.dumps(payload).encode()}}

    if self.settings.cloud_run_invoker_service_account:
      task["http_request"]["oidc_token"] = {"service_account_email": self.settings.cloud_run_invoker_service_account}

    parent = self.settings.cloud_tasks_queue_path

    try:
      response = self.client.create_task(request={"parent": parent, "task": task})
      logger.info(f"Enqueued lesson task {response.name} for lesson {lesson_id}")
    except Exception as e:
      logger.error(f"Failed to enqueue lesson task for lesson {lesson_id}: {e}", exc_info=True)
      raise
