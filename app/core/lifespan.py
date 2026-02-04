import logging
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from app.core.firebase import initialize_firebase
from app.core.logging import _initialize_logging
from fastapi import FastAPI

# Background worker loop code removed in favor of Cloud Tasks / HTTP Dispatcher.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  """Ensure logging is correctly set up after uvicorn starts."""
  from app.config import get_settings

  settings = get_settings()
  logger = logging.getLogger("app.core.lifespan")

  try:
    _initialize_logging(settings)
    logger.info("Startup complete - logging verified.")

    # Initialize Firebase
    initialize_firebase()
    # In development, optionally apply migrations automatically to avoid runtime errors from missing tables/seeds.
    # Production deployments should keep migrations in a dedicated deploy step.
    auto_apply = (os.getenv("DYLEN_AUTO_APPLY_MIGRATIONS", "") or "").strip().lower() in {"1", "true", "yes", "on"}
    if auto_apply and settings.environment != "production":
      repo_root = Path(__file__).resolve().parents[2]
      subprocess.run([sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], check=True, cwd=repo_root)

  except Exception:
    logger.warning("Initial logging setup failed; will retry on lifespan.", exc_info=True)

  yield
