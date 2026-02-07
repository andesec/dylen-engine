"""Run per-migration seed scripts in Alembic revision order."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

# Ensure repo root is on sys.path so local imports work when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.migration_order import load_migration_chain

logger = logging.getLogger("scripts.run_seed_scripts")


@dataclass(frozen=True)
class SeedScript:
  """Metadata describing a seed script file."""

  revision: str
  path: Path


def _normalize_async_dsn(raw_dsn: str) -> str:
  """Normalize DSNs so scripts consistently use asyncpg."""
  # Convert sync postgres URLs to asyncpg for consistent async execution.
  dsn = raw_dsn.strip()
  if dsn.startswith("postgresql+asyncpg://"):
    return dsn
  if dsn.startswith("postgresql://"):
    return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
  if dsn.startswith("postgres://"):
    return dsn.replace("postgres://", "postgresql+asyncpg://", 1)
  return dsn


async def _table_exists(connection: AsyncConnection, *, table_name: str, schema: str | None = None) -> bool:
  """Return True when a table exists in the target schema."""
  # Default to public schema when none is provided.
  resolved_schema = schema or "public"
  # Query information_schema to detect table presence.
  statement = text(
    """
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = :schema
      AND table_name = :table_name
      AND table_type = 'BASE TABLE'
    LIMIT 1
    """
  )
  result = await connection.execute(statement, {"schema": resolved_schema, "table_name": table_name})
  return result.first() is not None


async def _column_exists(connection: AsyncConnection, *, table_name: str, column_name: str, schema: str | None = None) -> bool:
  """Return True when a column exists on the specified table."""
  # Default to public schema when none is provided.
  resolved_schema = schema or "public"
  # Query information_schema to detect column presence.
  statement = text(
    """
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = :schema
      AND table_name = :table_name
      AND column_name = :column_name
    LIMIT 1
    """
  )
  result = await connection.execute(statement, {"schema": resolved_schema, "table_name": table_name, "column_name": column_name})
  return result.first() is not None


async def _ensure_seed_versions_table(connection: AsyncConnection) -> None:
  """Create or repair the seed_versions table so seed tracking is reliable."""
  # Create the seed_versions table when missing.
  if not await _table_exists(connection, table_name="seed_versions"):
    await connection.execute(
      text(
        """
        CREATE TABLE seed_versions (
          revision TEXT PRIMARY KEY,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
      )
    )
    return

  # Ensure required columns exist for legacy/partial tables.
  if not await _column_exists(connection, table_name="seed_versions", column_name="revision"):
    await connection.execute(text("ALTER TABLE seed_versions ADD COLUMN revision TEXT"))
    await connection.execute(text("ALTER TABLE seed_versions ADD PRIMARY KEY (revision)"))

  if not await _column_exists(connection, table_name="seed_versions", column_name="applied_at"):
    await connection.execute(text("ALTER TABLE seed_versions ADD COLUMN applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"))


def _seed_scripts_dir() -> Path:
  """Resolve the seed scripts directory from the repo root."""
  # Anchor on this script location to resolve the repo root.
  return Path(__file__).resolve().parents[1] / "scripts" / "seeds"


def _load_seed_script(path: Path) -> ModuleType:
  """Load a seed script module from the given path."""
  # Load the module from disk using an importlib spec.
  spec = importlib.util.spec_from_file_location(path.stem, path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load seed script: {path}")

  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def _collect_seed_scripts() -> list[SeedScript]:
  """Collect seed scripts that match Alembic revisions."""
  # Build the list from Alembic's linear migration chain.
  chain = load_migration_chain()
  seeds_dir = _seed_scripts_dir()
  scripts: list[SeedScript] = []
  for info in chain:
    path = seeds_dir / f"{info.revision}.py"
    if not path.exists():
      # Seed scripts are optional; skip if missing.
      continue

    scripts.append(SeedScript(revision=info.revision, path=path))

  return scripts


async def _has_seed_applied(connection: AsyncConnection, *, revision: str) -> bool:
  """Return True when a seed revision is already recorded."""
  # Query the seed_versions table for the revision.
  result = await connection.execute(text("SELECT 1 FROM seed_versions WHERE revision = :revision"), {"revision": revision})
  return result.first() is not None


async def _mark_seed_applied(connection: AsyncConnection, *, revision: str) -> None:
  """Record a seed revision in seed_versions."""
  # Insert the revision in an idempotent way.
  await connection.execute(
    text(
      """
      INSERT INTO seed_versions (revision)
      VALUES (:revision)
      ON CONFLICT (revision) DO NOTHING
      """
    ),
    {"revision": revision},
  )


async def _run_seed_scripts(*, dsn: str) -> None:
  """Run seed scripts in revision order with idempotent tracking."""
  # Create an async engine for database operations.
  engine = create_async_engine(dsn, future=True)
  try:
    async with engine.begin() as connection:
      # Enforce the public schema for seed operations.
      await connection.execute(text("SET LOCAL search_path TO public"))
      # Ensure seed_versions exists before any queries reference it.
      await _ensure_seed_versions_table(connection)
      # Collect the ordered seed scripts to execute.
      scripts = _collect_seed_scripts()
      for script in scripts:
        # Skip already-applied seed revisions.
        if await _has_seed_applied(connection, revision=script.revision):
          message = f"Skipping seed script (already applied): {script.revision} ({script.path.name})"
          print(message)
          logger.info(message)
          continue

        # Load and execute the seed script's async entrypoint.
        module = _load_seed_script(script.path)
        seed_func = getattr(module, "seed", None)
        if seed_func is None:
          raise RuntimeError(f"Seed script missing seed() function: {script.path}")

        # Enforce async seed functions for consistent execution.
        if not inspect.iscoroutinefunction(seed_func):
          raise RuntimeError(f"Seed script seed() must be async: {script.path}")

        # Execute the seed script against the shared connection.
        message = f"Running seed script: {script.revision} ({script.path.name})"
        print(message)
        logger.info(message)
        await seed_func(connection)
        # Record completion in seed_versions.
        await _mark_seed_applied(connection, revision=script.revision)
  finally:
    # Dispose the engine to close connections cleanly.
    await engine.dispose()


def main() -> None:
  """Entrypoint for running seed scripts from the command line."""
  # Configure base logging for CLI usage.
  logging.basicConfig(level=logging.INFO)
  # Read the database DSN from the environment to avoid accidental targeting.
  raw_dsn = (os.getenv("DYLEN_PG_DSN") or "").strip()
  if not raw_dsn:
    raise RuntimeError("DYLEN_PG_DSN must be set to run seed scripts.")

  normalized_dsn = _normalize_async_dsn(raw_dsn)
  asyncio.run(_run_seed_scripts(dsn=normalized_dsn))


if __name__ == "__main__":
  main()
