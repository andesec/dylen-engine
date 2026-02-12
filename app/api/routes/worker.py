from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.services.jobs import process_job_sync
from app.storage.factory import _get_jobs_repo

router = APIRouter()
logger = logging.getLogger(__name__)


class LessonGenerationTask(BaseModel):
  lesson_id: str
  job_id: str
  params: dict[str, Any]
  user_id: str


@router.post("/process-lesson", status_code=status.HTTP_200_OK)
async def process_lesson_endpoint(task: LessonGenerationTask, settings: Settings = Depends(get_settings), authorization: str | None = Header(default=None)) -> dict[str, str]:
  """Worker endpoint to process lesson generation."""
  # Secure internal worker endpoint with the shared task secret when configured.
  if not settings.task_secret:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Task authentication is not configured.")
  expected = f"Bearer {settings.task_secret}"
  if not secrets.compare_digest((authorization or ""), expected):
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid task secret.")
  logger.info("Received lesson generation task for job %s", task.job_id)

  jobs_repo = _get_jobs_repo(settings)
  job = await jobs_repo.get_job(task.job_id)

  if not job:
    logger.error("Job %s not found during worker processing.", task.job_id)
    return {"status": "job_not_found"}

  # Idempotency check
  if job.status in ("running", "processing", "done"):
    logger.info("Job %s is already %s. Skipping.", task.job_id, job.status)
    return {"status": "skipped"}

  processed = await process_job_sync(task.job_id, settings)
  if processed is None:
    return {"status": "error"}
  if processed.status == "done":
    return {"status": "ok"}
  if processed.status == "canceled":
    return {"status": "canceled"}
  if processed.status == "error":
    return {"status": "error"}
  return {"status": "processing"}
