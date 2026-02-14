import logging
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from app.core.env_contract import EnvContractError, validate_runtime_env_or_raise
from app.core.logging import _initialize_logging
from fastapi import FastAPI
from scripts.ensure_superadmin_user import ensure_superadmin_user

# Background worker loop code removed in favor of Cloud Tasks / HTTP Dispatcher.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  """Ensure logging is correctly set up after uvicorn starts."""
  from app.config import get_settings

  # **PERFORMANCE**: Track startup time to measure cold start optimization impact.
  startup_start_time = time.perf_counter()

  # Load settings for startup initialization.
  settings = get_settings()
  # Create a module logger for lifespan events.
  logger = logging.getLogger("app.core.lifespan")

  try:
    # Initialize logging with configured settings.
    phase_start = time.perf_counter()
    _initialize_logging(settings)
    logger.info("Startup phase=logging_init duration_ms=%.1f", (time.perf_counter() - phase_start) * 1000)

    # Emit a startup confirmation log for operators.
    logger.info("Startup complete - logging verified.")
    # Log effective LLM audit toggles so cloud misconfiguration is visible immediately.
    logger.info("LLM audit config enabled=%s pg_dsn_set=%s", bool(settings.llm_audit_enabled), bool(settings.pg_dsn))

    # Enforce startup env contracts before app dependencies are initialized.
    phase_start = time.perf_counter()
    validate_runtime_env_or_raise(logger=logger, target="service")
    logger.info("Startup phase=env_validation duration_ms=%.1f", (time.perf_counter() - phase_start) * 1000)

    # Decide whether to auto-apply migrations based on the runtime flag.
    auto_apply = (os.getenv("DYLEN_AUTO_APPLY_MIGRATIONS", "") or "").strip().lower() in {"1", "true", "yes", "on"}
    # Apply migrations at startup when the flag is enabled.
    if auto_apply:
      phase_start = time.perf_counter()
      # Avoid startup migrations in production-like environments unless explicitly forced.
      if settings.environment in {"production", "prod", "stage", "staging"} and not _parse_env_bool(os.getenv("DYLEN_FORCE_STARTUP_MIGRATIONS")):
        logger.info("Skipping startup migrations for environment=%s", settings.environment)
      else:
        # Log the configured DSN without credentials for troubleshooting.
        logger.info("Auto-apply migrations enabled; DYLEN_PG_DSN=%s", _redact_dsn(settings.pg_dsn))
        repo_root = Path(__file__).resolve().parents[2]
        # Stream migrator output so logs appear in real-time.
        subprocess.run([sys.executable, "scripts/migrate_with_lock.py"], check=True, cwd=repo_root)
      logger.info("Startup phase=migrations duration_ms=%.1f", (time.perf_counter() - phase_start) * 1000)

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
  phase_start = time.perf_counter()
  await ensure_superadmin_user()
  logger.info("Startup phase=superadmin_bootstrap duration_ms=%.1f", (time.perf_counter() - phase_start) * 1000)

  # **PERFORMANCE**: Log total startup duration for cold start monitoring.
  total_startup_ms = (time.perf_counter() - startup_start_time) * 1000
  logger.info("Startup COMPLETE total_duration_ms=%.1f environment=%s", total_startup_ms, settings.environment)

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


def _parse_env_bool(value: str | None) -> bool:
  """Parse a boolean-like environment value."""
  # Treat common truthy values as enabled.
  if value is None:
    return False
  return value.strip().lower() in {"1", "true", "yes", "on"}
