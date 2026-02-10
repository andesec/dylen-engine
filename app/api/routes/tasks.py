from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.services.jobs import process_job_sync

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)


class TaskPayload(BaseModel):
  job_id: str


@router.post("/process-job", status_code=status.HTTP_200_OK)
async def process_job_task(payload: TaskPayload, background_tasks: BackgroundTasks, settings: Annotated[Settings, Depends(get_settings)], authorization: str | None = Header(default=None)) -> dict[str, str]:
  """
  Handler for Cloud Tasks (and local simulation).
  Accepts the task quickly and processes the job in the background to avoid client disconnects/timeouts.
  """
  # Secure-by-default: internal task endpoints must be authenticated to avoid arbitrary job execution.
  if not settings.task_secret:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Task authentication is not configured.")
  expected = f"Bearer {settings.task_secret}"
  if not secrets.compare_digest((authorization or ""), expected):
    logger.warning("Unauthorized access attempt to /process-job")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid task secret.")

  logger.info("Received task for job %s", payload.job_id)
  # Run processing asynchronously so task dispatchers (local-http, Cloud Tasks) can get a fast 2xx response.
  background_tasks.add_task(process_job_sync, payload.job_id, settings)
  return {"status": "accepted"}
