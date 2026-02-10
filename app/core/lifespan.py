import logging
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from app.core.database import get_db_engine
from app.core.env_contract import EnvContractError, validate_runtime_env_or_raise
from app.core.firebase import initialize_firebase
from app.core.logging import _initialize_logging
from app.services.storage_client import build_storage_client
from fastapi import FastAPI
from scripts.ensure_superadmin_user import ensure_superadmin_user
from sqlalchemy import text

# Background worker loop code removed in favor of Cloud Tasks / HTTP Dispatcher.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  """Ensure logging is correctly set up after uvicorn starts."""
  from app.config import get_settings

  # Load settings for startup initialization.
  settings = get_settings()
  # Create a module logger for lifespan events.
  logger = logging.getLogger("app.core.lifespan")

  try:
    # Initialize logging with configured settings.
    _initialize_logging(settings)
    # Emit a startup confirmation log for operators.
    logger.info("Startup complete - logging verified.")
    # Enforce startup env contracts before app dependencies are initialized.
    validate_runtime_env_or_raise(logger=logger, target="service")

    # Initialize Firebase before handling requests.
    initialize_firebase()
    # Ensure the illustration bucket exists before media jobs begin.
    try:
      storage_client = build_storage_client(settings)
      await storage_client.ensure_bucket()
      logger.info("Illustration bucket ensured: %s", storage_client.bucket_name)
    except Exception as exc:  # noqa: BLE001
      logger.warning("Failed to ensure illustration bucket at startup: %s", exc)
    # Decide whether to auto-apply migrations based on the runtime flag.
    auto_apply = (os.getenv("DYLEN_AUTO_APPLY_MIGRATIONS", "") or "").strip().lower() in {"1", "true", "yes", "on"}
    # Apply migrations at startup when the flag is enabled.
    if auto_apply:
      # Avoid startup migrations in production-like environments unless explicitly forced.
      if settings.environment in {"production", "prod", "stage", "staging"} and not _parse_env_bool(os.getenv("DYLEN_FORCE_STARTUP_MIGRATIONS")):
        logger.info("Skipping startup migrations for environment=%s", settings.environment)
      else:
        # Log the configured DSN without credentials for troubleshooting.
        logger.info("Auto-apply migrations enabled; DYLEN_PG_DSN=%s", _redact_dsn(settings.pg_dsn))
        repo_root = Path(__file__).resolve().parents[2]
        # Stream migrator output so logs appear in real-time.
        subprocess.run([sys.executable, "scripts/migrate_with_lock.py"], check=True, cwd=repo_root)
        # Log the database state after migrations to confirm the runtime schema.
        await _log_db_state(logger=logger)

  except EnvContractError:
    # Fail-fast when required startup configuration is missing or invalid.
    logger.error("Environment contract failed; refusing to start the service.", exc_info=True)
    raise

  except Exception as exc:
    # Log initialization failures but allow the app to continue starting.
    if isinstance(exc, subprocess.CalledProcessError):
      logger.warning("Initial logging setup failed; migrator returned non-zero exit status.", exc_info=True)
    else:
      logger.warning("Initial logging setup failed; will retry on lifespan.", exc_info=True)

  # Enforce strict superadmin bootstrap so admin login remains guaranteed after startup.
  await ensure_superadmin_user()

  yield


def _redact_dsn(raw: str | None) -> str:
  """Redact credentials from a DSN while keeping host/db visible."""
  # Provide a stable placeholder when the DSN is missing.
  if not raw:
    return "<unset>"

  # Parse the DSN so we can safely strip credentials.
  parsed = urlparse(raw)
  # Guard against malformed DSNs without a scheme.
  if not parsed.scheme:
    return "<invalid>"

  # Build a sanitized netloc with username and host metadata only.
  user = parsed.username or ""
  host = parsed.hostname or ""
  port = f":{parsed.port}" if parsed.port else ""
  netloc = f"{user}@{host}{port}" if user else f"{host}{port}"
  # Preserve the database name when available.
  database = parsed.path.lstrip("/")
  path = f"/{database}" if database else ""
  return f"{parsed.scheme}://{netloc}{path}"


async def _log_db_state(*, logger: logging.Logger) -> None:
  """Log search_path, current schema, and notifications table presence."""
  # Build the runtime engine so we can inspect the active connection state.
  engine = get_db_engine()
  if engine is None:
    logger.warning("Database engine unavailable; cannot inspect runtime schema state.")
    return

  # Open a connection so we can query the current schema and tables.
  async with engine.connect() as connection:
    # Query the active search_path for this connection.
    search_path = await connection.execute(text("SHOW search_path"))
    search_path_value = str(search_path.scalar_one())
    # Query the active schema used by the connection.
    current_schema = await connection.execute(text("SELECT current_schema()"))
    current_schema_value = str(current_schema.scalar_one())
    # Check for the notifications table in the public schema.
    table_query = """
      SELECT 1
      FROM information_schema.tables
      WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
        AND table_name = 'notifications'
      LIMIT 1
      """
    table_result = await connection.execute(text(table_query))
    notifications_exists = table_result.first() is not None
    # Emit a summary for debugging mismatched schemas.
    logger.info("Runtime DB state search_path=%s current_schema=%s notifications_table=%s", search_path_value, current_schema_value, notifications_exists)


def _parse_env_bool(value: str | None) -> bool:
  """Parse a boolean-like environment value."""
  # Treat common truthy values as enabled.
  if value is None:
    return False
  return value.strip().lower() in {"1", "true", "yes", "on"}
