from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models import GenerateLessonRequest
from app.config import Settings, get_settings
from app.core.database import get_db
from app.services.lessons import process_lesson_generation
from app.services.users import get_user_by_id, get_user_subscription_tier
from app.storage.factory import _get_jobs_repo

router = APIRouter()
logger = logging.getLogger(__name__)

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class LessonGenerationTask(BaseModel):
  lesson_id: str
  job_id: str
  params: dict[str, Any]
  user_id: str


@router.post("/process-lesson", status_code=status.HTTP_200_OK)
async def process_lesson_endpoint(
  task: LessonGenerationTask,
  settings: Settings = Depends(get_settings),
  db_session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
  """Worker endpoint to process lesson generation."""
  logger.info("Received lesson generation task for job %s", task.job_id)

  jobs_repo = _get_jobs_repo(settings)
  job = await jobs_repo.get_job(task.job_id)

  if not job:
    logger.error("Job %s not found during worker processing.", task.job_id)
    return {"status": "job_not_found"}

  # Idempotency check
  if job.status in ("processing", "done"):
    logger.info("Job %s is already %s. Skipping.", task.job_id, job.status)
    return {"status": "skipped"}

  # Update to processing
  # We append to logs
  current_logs = job.logs or []
  updated_job = await jobs_repo.update_job(task.job_id, status="processing", phase="processing", logs=current_logs + ["Worker started processing."])
  if updated_job:
    current_logs = updated_job.logs or current_logs

  try:
    # Hydrate user
    try:
      u_uuid = uuid.UUID(task.user_id)
    except ValueError:
      logger.error("Invalid user_id format: %s", task.user_id)
      raise ValueError("Invalid user_id") from None

    user = await get_user_by_id(db_session, u_uuid)
    if not user:
      raise ValueError(f"User {task.user_id} not found.")

    # Parse request
    request = GenerateLessonRequest.model_validate(task.params)

    # Get tier
    tier_id, _ = await get_user_subscription_tier(db_session, user.id)

    # Process
    result = await process_lesson_generation(
      request=request, lesson_id=task.lesson_id, settings=settings, current_user=user, db_session=db_session, tier_id=tier_id, idempotency_key=job.idempotency_key
    )

    # Update job success
    # Refresh job to get latest logs if needed? No, we just append.
    # Actually, update_job replaces fields. We should fetch fresh logs?
    # Or just append to what we had at start + "Worker started".
    # Since we are single threaded per job largely, it's fine.
    await jobs_repo.update_job(
      task.job_id,
      status="done",
      phase="done",
      progress=100.0,
      completed_at=time.strftime(_DATE_FORMAT, time.gmtime()),
      result_json=result.model_dump(mode="json"),
      logs=current_logs + ["Worker started processing.", "Worker completed successfully."],
    )

  except Exception as e:
    logger.error("Job %s failed: %s", task.job_id, e, exc_info=True)
    await jobs_repo.update_job(
      task.job_id, status="error", phase="error", logs=current_logs + ["Worker started processing.", f"Error: {e!s}"], completed_at=time.strftime(_DATE_FORMAT, time.gmtime())
    )
    return {"status": "error", "detail": str(e)}

  return {"status": "ok"}
