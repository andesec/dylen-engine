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
import zlib
from pathlib import Path

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


def _lock_key() -> int:
  """Return a stable advisory lock key for Dylen migrations."""
  # Use CRC32 to produce a stable 32-bit value compatible with pg_advisory_lock(bigint).
  return int(zlib.crc32(b"dylen-engine-alembic-migrate"))


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
  """Run migrations with guardrails and a database-level lock."""
  logging.basicConfig(level=logging.INFO)
  raw_dsn = (os.getenv("DYLEN_PG_DSN") or "").strip()
  if not raw_dsn:
    raise RuntimeError("DYLEN_PG_DSN must be set to run migrations.")
  dsn = _normalize_async_dsn(raw_dsn)
  alembic_ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
  if not alembic_ini_path.exists():
    raise RuntimeError(f"Missing Alembic config at {alembic_ini_path}.")
  engine = _build_engine(dsn=dsn)
  async with engine.connect() as connection:
    # Acquire an advisory lock so only one migrator runs at a time.
    key = _lock_key()
    logger.info("Acquiring migration lock key=%s", key)
    await connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
    try:
      # Guard against inconsistent schema/history states that cause duplicate DDL failures.
      await _guard_schema_history_state(connection)
      logger.info("Running alembic upgrade head")
      await connection.run_sync(_run_upgrade_sync, alembic_ini_path)
    finally:
      # Always release the lock even when migrations fail so subsequent attempts can proceed.
      logger.info("Releasing migration lock key=%s", key)
      await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
  await engine.dispose()


def main() -> None:
  """Run migrations with guardrails and a database-level lock."""
  asyncio.run(_run_migrations())


if __name__ == "__main__":
  main()
