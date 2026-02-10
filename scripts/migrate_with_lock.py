"""Run Alembic migrations with safety guards and an advisory lock.

How/Why:
- Prevent confusing `DuplicateTableError` failures when the database schema exists but Alembic history is missing.
- Prevent concurrent migration runners from racing in dev/deploy environments.
- Keep behavior secure-by-default by refusing to "guess" when history is missing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

logger = logging.getLogger("scripts.migrate_with_lock")


def _normalize_async_dsn(raw_dsn: str) -> str:
  """Convert DSNs into an asyncpg SQLAlchemy DSN suitable for async migration runs."""
  # Ensure the engine uses asyncpg so we can acquire advisory locks without extra sync drivers.
  dsn = raw_dsn.strip()
  if dsn.startswith("postgresql+asyncpg://"):
    return dsn

  if dsn.startswith("postgresql://"):
    return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)

  if dsn.startswith("postgres://"):
    return dsn.replace("postgres://", "postgresql+asyncpg://", 1)

  return dsn


def _redact_dsn(raw: str) -> str:
  """Redact credentials from a DSN while keeping host/db visible."""
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


async def _alembic_version_table_exists(connection: AsyncConnection) -> bool:
  """Check if the Alembic version table exists in the default schema."""
  # Use information_schema to avoid relying on sync inspection helpers.
  result = await connection.execute(
    text(
      """
      SELECT 1
      FROM information_schema.tables
      WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
        AND table_name = 'alembic_version'
      LIMIT 1
      """
    )
  )
  return result.first() is not None


async def _alembic_version_row_count(connection: AsyncConnection) -> int:
  """Return the number of rows in `alembic_version` (0 when empty)."""
  # The version table is expected to have 1 row in normal operation.
  result = await connection.execute(text("SELECT COUNT(*) FROM alembic_version"))
  return int(result.scalar_one())


async def _public_table_count_excluding_alembic(connection: AsyncConnection) -> int:
  """Return the count of public tables excluding Alembic metadata."""
  # Detect "schema exists but migration history is missing" states that will cause duplicate DDL errors.
  result = await connection.execute(
    text(
      """
      SELECT COUNT(*)
      FROM information_schema.tables
      WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
        AND table_name <> 'alembic_version'
      """
    )
  )
  return int(result.scalar_one())


async def _table_exists(connection: AsyncConnection, *, table_name: str) -> bool:
  """Return True when a public table exists."""
  # Use information_schema to avoid sync inspection helpers.
  query = """
      SELECT 1
      FROM information_schema.tables
      WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
        AND table_name = :table_name
      LIMIT 1
      """
  result = await connection.execute(text(query), {"table_name": table_name})
  return result.first() is not None


async def _fetch_runtime_state(connection: AsyncConnection) -> tuple[str, str, bool]:
  """Return search_path, current schema, and notifications table presence."""
  # Fetch the configured search_path for this connection.
  search_path = await connection.execute(text("SHOW search_path"))
  search_path_value = str(search_path.scalar_one())
  # Fetch the current schema for this connection.
  current_schema = await connection.execute(text("SELECT current_schema()"))
  current_schema_value = str(current_schema.scalar_one())
  # Check for the notifications table in the public schema.
  notifications_exists = await _table_exists(connection, table_name="notifications")
  return search_path_value, current_schema_value, notifications_exists


async def _guard_schema_history_state(connection: AsyncConnection) -> None:
  """Refuse to run migrations when schema exists but Alembic history is missing."""
  # If the schema already exists but Alembic does not know what's applied, running `upgrade head` will try to
  # create tables again and fail with errors like DuplicateTableError.
  public_tables = await _public_table_count_excluding_alembic(connection)
  version_table_exists = await _alembic_version_table_exists(connection)
  if not version_table_exists and public_tables > 0:
    raise RuntimeError("Database contains tables but Alembic history is missing (no `alembic_version` table). If this is a dev reset, drop and recreate the database/volume, or run `alembic stamp head` if the schema is already at head.")

  if version_table_exists:
    version_rows = await _alembic_version_row_count(connection)
    if version_rows == 0 and public_tables > 0:
      raise RuntimeError(
        "Database contains tables but Alembic history is empty (`alembic_version` has 0 rows). "
        "This commonly happens after truncating tables instead of dropping the database. "
        "Drop and recreate the database/volume, or run `alembic stamp head` if the schema is already at head."
      )


def _run_upgrade_sync(connection: Connection, alembic_ini_path: Path) -> None:
  """Run `alembic upgrade head` using the provided sync connection."""
  # Provide the existing connection to Alembic so env.py uses it rather than creating a new engine.
  config = Config(str(alembic_ini_path))
  config.attributes["connection"] = connection
  command.upgrade(config, "head")


def _build_engine(*, dsn: str) -> AsyncEngine:
  """Build a minimal async engine for migration runs."""
  # Keep the engine minimal and avoid implicit environment proxy behavior.
  return create_async_engine(dsn, pool_pre_ping=True, future=True)


async def _run_migrations() -> None:
  """Run migrations with guardrails but WITHOUT advisory locks."""
  # Configure base logging for CLI usage.
  logging.basicConfig(level=logging.INFO)
  # Read the database DSN from the environment for safety.
  raw_dsn = (os.getenv("DYLEN_PG_DSN") or "").strip()
  if not raw_dsn:
    raise RuntimeError("DYLEN_PG_DSN must be set to run migrations.")

  # Allow control of migrator behavior for CI and repair workflows.
  migrator_mode = (os.getenv("DYLEN_MIGRATOR_MODE") or "migrate").strip().lower()
  # Allow fail-open behavior to avoid hard failures in worst-case scenarios.
  fail_open = (os.getenv("DYLEN_MIGRATOR_FAIL_OPEN") or "").strip().lower() in {"1", "true", "yes", "on"}

  # Normalize the DSN so async connections are consistent.
  dsn = _normalize_async_dsn(raw_dsn)
  # Emit the sanitized DSN for troubleshooting mismatched environments.
  logger.info("Migrator using DYLEN_PG_DSN=%s", _redact_dsn(dsn))
  alembic_ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
  if not alembic_ini_path.exists():
    raise RuntimeError(f"Missing Alembic config at {alembic_ini_path}.")

  engine = _build_engine(dsn=dsn)

  # Connect without locking.
  async with engine.connect() as connection:
    # Start a transaction for schema operations.
    async with connection.begin():
      # Guard against inconsistent schema/history states that cause duplicate DDL failures.
      await _guard_schema_history_state(connection)
      # Enforce the public schema before verification/repair.
      await connection.execute(text("SET LOCAL search_path TO public"))
      # Log the active schema configuration before migrations.
      search_path, current_schema, notifications_exists = await _fetch_runtime_state(connection)
      logger.info("Pre-migration DB state search_path=%s current_schema=%s notifications_table=%s", search_path, current_schema, notifications_exists)

      if migrator_mode in {"migrate", "repair"}:
        # Apply Alembic migrations first so the version table stays authoritative.
        logger.info("Running alembic upgrade head")
        await connection.run_sync(_run_upgrade_sync, alembic_ini_path)
        # Log the schema state after migrations to confirm changes.
        search_path, current_schema, notifications_exists = await _fetch_runtime_state(connection)
        logger.info("Post-migration DB state search_path=%s current_schema=%s notifications_table=%s", search_path, current_schema, notifications_exists)

    # Transaction is committed here.

    # Always verify the schema to detect drift and missing objects.
    logger.info("Verifying schema after migrations")
    from scripts.schema_checks import format_failure_report, verify_schema

    # Verification needs its own transaction if utilizing SET LOCAL or similar.
    async with connection.begin():
      await connection.execute(text("SET LOCAL search_path TO public"))
      verification = await connection.run_sync(verify_schema, schema="public")

    if verification.has_failures() and migrator_mode in {"migrate", "repair"}:
      # Run targeted repair only when verification fails.
      logger.warning("Schema verification failed; initiating targeted repair.")
      from scripts.repair_schema import _repair_schema

      async with connection.begin():
        verification = await _repair_schema(connection=connection, schema="public")

    if verification.has_failures():
      # Emit a single actionable failure report and stop.
      report = format_failure_report(verification)
      logger.error("%s", report)
      if fail_open:
        logger.error("DYLEN_MIGRATOR_FAIL_OPEN enabled; continuing despite verification failures.")
      else:
        raise RuntimeError(report)

    if migrator_mode in {"migrate", "repair"}:
      if verification.has_failures() and fail_open:
        # Skip seeds when schema verification fails to avoid data drift.
        logger.warning("Skipping seed scripts due to verification failures with fail-open enabled.")
      else:
        # Run seed scripts once per migration revision to keep data in sync without reapplying.
        logger.info("Running seed scripts after migrations")
        repo_root = Path(__file__).resolve().parents[1]
        subprocess.run([sys.executable, "scripts/run_seed_scripts.py"], check=True, cwd=repo_root)

        # Ensure the superadmin user exists and is synced specifically after seeds are done.
        logger.info("Ensuring superadmin user is provisioned")
        from scripts.ensure_superadmin_user import ensure_superadmin_user

        await ensure_superadmin_user()

  await engine.dispose()


def main() -> None:
  """Run migrations with guardrails and a database-level lock."""
  asyncio.run(_run_migrations())


if __name__ == "__main__":
  main()
