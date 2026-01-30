from __future__ import annotations

from functools import lru_cache

from app.config import Settings
from app.services.tasks.gcp import CloudTasksEnqueuer
from app.services.tasks.interface import TaskEnqueuer
from app.services.tasks.local import LocalHttpEnqueuer


def get_task_enqueuer(settings: Settings) -> TaskEnqueuer:
  """Factory to get the configured task enqueuer."""
  if settings.task_service_provider == "gcp":
    return CloudTasksEnqueuer(settings)
  return LocalHttpEnqueuer(settings)
