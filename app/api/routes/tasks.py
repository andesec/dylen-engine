from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.services.jobs import process_job_sync

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)


class TaskPayload(BaseModel):
  job_id: str


@router.post("/process-job", status_code=status.HTTP_200_OK)
async def process_job_task(payload: TaskPayload, settings: Annotated[Settings, Depends(get_settings)], authorization: str | None = Header(default=None)) -> dict[str, str]:
  """
  Handler for Cloud Tasks (and local simulation).
  Executes the job synchronously so the task queue knows when it's done.
  """
  # Secure-by-default: internal task endpoints must be authenticated to avoid arbitrary job execution.
  if not settings.task_secret:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Task authentication is not configured.")
  expected = f"Bearer {settings.task_secret}"
  if not secrets.compare_digest((authorization or ""), expected):
    logger.warning("Unauthorized access attempt to /process-job")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid task secret.")

  logger.info("Received task for job %s", payload.job_id)

  result = await process_job_sync(payload.job_id, settings)

  if result is None or result.status == "error":
    # Even if HTTP 200 (to satisfy Cloud Tasks), return truthful status in body
    return {"status": "error"}

  return {"status": "ok"}
