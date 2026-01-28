import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.database import Base, get_db_engine
from app.core.firebase import initialize_firebase
from app.core.logging import _initialize_logging

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

    # Create database tables if database is configured
    db_engine = get_db_engine()
    if db_engine:
      async with db_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

  except Exception:
    logger.warning("Initial logging setup failed; will retry on lifespan.", exc_info=True)

  yield
