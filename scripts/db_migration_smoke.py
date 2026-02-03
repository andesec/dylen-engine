from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine


def _normalize_async_dsn(dsn: str) -> str:
  """Normalize sync DSNs so Alembic uses the async driver consistently."""
  # Convert sync postgres URLs to the asyncpg driver used by runtime.
  if dsn.startswith("postgresql://"):
    return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)

  return dsn


def _build_temp_database_url(dsn: str, *, label: str) -> tuple[str, str, str]:
  """Create a temp database URL pair to isolate each smoke-test run."""
  # Use a timestamped DB name to avoid collisions in CI.
  base_url = make_url(dsn)
  base_name = base_url.database or "postgres"
  suffix = int(time.time() * 1000)
  temp_db_name = f"{base_name}_{label}_{suffix}"
  admin_url = base_url.set(database="postgres")
  temp_url = base_url.set(database=temp_db_name)
  return temp_url.render_as_string(hide_password=False), admin_url.render_as_string(hide_password=False), temp_db_name


def _load_alembic_config() -> Config:
  """Load Alembic config so revision inspection matches repo settings."""
  # Assume repo_root is the parent of the scripts directory
  repo_root = Path(__file__).resolve().parents[1]
  backend_dir = repo_root

  # 1. Validate alembic.ini exists
  if not (backend_dir / "alembic.ini").exists():
    print(f"Error: alembic.ini not found at {backend_dir / 'alembic.ini'}")
    sys.exit(1)
  config_path = backend_dir / "alembic.ini"
  script_path = backend_dir / "alembic"
  config = Config(str(config_path))
  # Override script_location so alembic runs from the repo root in CI.
  config.set_main_option("script_location", str(script_path))
  return config


def _previous_revision(config: Config) -> str | None:
  """Resolve the immediate previous revision to validate upgrade paths."""
  # Enforce a single head to keep the upgrade path unambiguous.
  script = ScriptDirectory.from_config(config)
  heads = script.get_heads()
  if len(heads) != 1:
    raise RuntimeError("Multiple Alembic heads detected; resolve before running upgrade-from-previous.")

  head_revision = script.get_revision(heads[0])
  if not head_revision:
    return None

  down_revision = head_revision.down_revision
  if not down_revision:
    return None

  if isinstance(down_revision, (tuple, list)):
    if len(down_revision) != 1:
      raise RuntimeError("Merge revisions detected; upgrade-from-previous requires a single parent.")

    return str(down_revision[0])

  return str(down_revision)


def _run_alembic(args: list[str], env: dict[str, str]) -> None:
  """Run Alembic via subprocess so env.py reads the correct variables."""
  # Resolve alembic.ini from the repository root to avoid cwd issues.
  # 3. Get current head
  config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
  command = [sys.executable, "-m", "alembic", "-c", str(config_path), *args]
  subprocess.run(command, check=True, env=env)


def _create_database(admin_url: str, db_name: str) -> None:
  """Create a temporary database for migration smoke tests."""

  # Use AUTOCOMMIT so CREATE DATABASE is allowed.
  async def _create() -> None:
    """Create the database via a short-lived async engine."""
    # Build a short-lived engine for database creation.
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
      async with engine.connect() as connection:
        # Issue CREATE DATABASE with explicit quoting to avoid naming issues.
        await connection.execute(text(f'CREATE DATABASE "{db_name}"'))

    finally:
      await engine.dispose()

  asyncio.run(_create())


def _drop_database(admin_url: str, db_name: str) -> None:
  """Drop the temporary database after migration tests complete."""

  # Use AUTOCOMMIT so DROP DATABASE is allowed.
  async def _drop() -> None:
    """Drop the database via a short-lived async engine."""
    # Build a short-lived engine for database cleanup.
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
      async with engine.connect() as connection:
        # Drop the database to keep CI environments clean.
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))

    finally:
      await engine.dispose()

  asyncio.run(_drop())


def _run_mode(*, dsn: str, allowed_origins: str, mode: str, downgrade: bool) -> None:
  """Run one smoke-test path against a fresh ephemeral database."""
  # Create a temporary database to isolate each smoke-test run.
  temp_url, admin_url, temp_name = _build_temp_database_url(dsn, label=mode.replace("_", "-"))
  _create_database(admin_url, temp_name)
  # Prepare environment variables for Alembic subprocess execution.
  env = os.environ.copy()
  env["DYLEN_PG_DSN"] = temp_url
  env["DYLEN_ALLOWED_ORIGINS"] = allowed_origins
  try:
    # Validate that fresh migrations apply cleanly.
    if mode == "fresh":
      _run_alembic(["upgrade", "head"], env)

    # Validate that upgrades from the previous revision succeed.
    if mode == "upgrade-from-previous":
      config = _load_alembic_config()
      previous = _previous_revision(config)
      if not previous:
        raise RuntimeError("No previous revision exists; cannot run upgrade-from-previous.")

      _run_alembic(["upgrade", previous], env)
      _run_alembic(["upgrade", "head"], env)

    # Optionally validate downgrade + re-upgrade.
    if downgrade:
      _run_alembic(["downgrade", "-1"], env)
      _run_alembic(["upgrade", "head"], env)

  finally:
    _drop_database(admin_url, temp_name)


def main() -> None:
  """Run migration smoke tests for fresh and upgrade paths."""
  # Parse CLI arguments so CI can select specific smoke-test modes.
  parser = argparse.ArgumentParser(description="Run Alembic migration smoke tests against a fresh database.")
  parser.add_argument("--mode", choices=["fresh", "upgrade-from-previous", "both"], default="fresh")
  parser.add_argument("--downgrade", action="store_true", help="Run downgrade -1 and re-upgrade after upgrade checks.")
  # Capture arguments once to keep control flow explicit.
  args = parser.parse_args()

  # Ensure required environment variables are set for settings validation.
  dsn = os.getenv("DYLEN_PG_DSN")
  allowed_origins = os.getenv("DYLEN_ALLOWED_ORIGINS")
  if not dsn:
    print("ERROR: DYLEN_PG_DSN is required for migration smoke tests.")
    sys.exit(1)

  if not allowed_origins:
    print("ERROR: DYLEN_ALLOWED_ORIGINS is required for migration smoke tests.")
    sys.exit(1)

  # Normalize the DSN to the async driver used by the application runtime.
  normalized_dsn = _normalize_async_dsn(dsn)
  if args.mode in {"fresh", "both"}:
    _run_mode(dsn=normalized_dsn, allowed_origins=allowed_origins, mode="fresh", downgrade=args.downgrade)

  if args.mode in {"upgrade-from-previous", "both"}:
    _run_mode(dsn=normalized_dsn, allowed_origins=allowed_origins, mode="upgrade-from-previous", downgrade=args.downgrade)


if __name__ == "__main__":
  main()
