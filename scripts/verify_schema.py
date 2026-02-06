"""Verify database schema against SQLAlchemy metadata."""

from __future__ import annotations

import asyncio
import logging
import os

from scripts.schema_checks import format_failure_report, verify_schema
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger("scripts.verify_schema")


def _normalize_async_dsn(raw_dsn: str) -> str:
  """Normalize DSNs so verification uses asyncpg."""
  # Convert sync postgres URLs to asyncpg for consistent async execution.
  dsn = raw_dsn.strip()
  if dsn.startswith("postgresql+asyncpg://"):
    return dsn
  if dsn.startswith("postgresql://"):
    return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
  if dsn.startswith("postgres://"):
    return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
  return dsn


def main() -> None:
  """Entrypoint for schema verification."""
  # Configure base logging for CLI usage.
  logging.basicConfig(level=logging.INFO)
  # Allow fail-open behavior for environments that must not hard-fail.
  fail_open = (os.getenv("DYLEN_MIGRATOR_FAIL_OPEN") or "").strip().lower() in {"1", "true", "yes", "on"}
  # Read the database DSN from the environment for safety.
  raw_dsn = (os.getenv("DYLEN_PG_DSN") or "").strip()
  if not raw_dsn:
    raise RuntimeError("DYLEN_PG_DSN must be set to verify schema.")

  # Normalize the DSN so async connections are consistent.
  normalized_dsn = _normalize_async_dsn(raw_dsn)
  # Create the async engine for verification.
  engine = create_async_engine(normalized_dsn, future=True)

  async def _runner() -> None:
    # Wrap execution so the engine always disposes.
    try:
      # Open a transaction so SET LOCAL applies within verification.
      async with engine.begin() as connection:
        # Enforce the public schema for verification.
        await connection.execute(text("SET LOCAL search_path TO public"))
        # Run schema verification against metadata.
        result = await connection.run_sync(verify_schema, schema="public")
        if result.has_failures():
          # Emit a single actionable failure report.
          report = format_failure_report(result)
          logger.error("%s", report)
          if fail_open:
            logger.error("DYLEN_MIGRATOR_FAIL_OPEN enabled; continuing despite verification failures.")
          else:
            raise RuntimeError(report)
        # Log success for operators and CI visibility.
        logger.info("Schema verification passed.")
    finally:
      # Dispose the engine to close connections cleanly.
      await engine.dispose()

  # Run the async verification flow.
  asyncio.run(_runner())


if __name__ == "__main__":
  main()
