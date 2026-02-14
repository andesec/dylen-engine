from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

# Add the engine package root to sys.path for model imports.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Import all ORM models so drift detection reflects the complete schema.
import app.schema.db_models  # noqa: E402, F401
from app.core.database import DATABASE_URL, Base  # noqa: E402
from app.core.migrations import build_migration_context_options  # noqa: E402


def _load_allowlist() -> list[str]:
  """Parse allowlist tokens so known-safe diffs can be ignored explicitly."""
  # Read allowlist tokens from environment to keep config out of code.
  raw = os.getenv("DYLEN_MIGRATION_DRIFT_ALLOWLIST", "")
  if not raw:
    return []

  # Split on commas and trim whitespace so tokens match diff output reliably.
  tokens = [item.strip() for item in raw.split(",") if item.strip()]
  return tokens


def _filter_diffs(diffs: list[Any], allowlist: list[str]) -> list[Any]:
  """Remove diffs that match allowlist tokens to keep drift checks explicit."""
  # Skip filtering when no allowlist tokens are configured.
  if not allowlist:
    return diffs

  # Keep only diffs that do not match any allowlist token.
  filtered: list[Any] = []
  for diff in diffs:
    diff_text = str(diff)
    if any(token in diff_text for token in allowlist):
      continue

    filtered.append(diff)

  return filtered


async def _collect_drift() -> list[Any]:
  """Compare live schema with metadata using Alembic's autogenerate engine."""
  # Fail fast when database configuration is missing.
  if not DATABASE_URL:
    raise RuntimeError("DYLEN_PG_DSN is not set, cannot run drift detection.")

  # Use the async engine so drift checks run against the runtime driver.
  engine = create_async_engine(DATABASE_URL)
  try:
    async with engine.connect() as connection:
      # Use a sync context for Alembic's autogenerate comparison.
      def _compare(sync_connection: Any) -> list[Any]:
        """Compare metadata against the active database connection."""
        # Build Alembic comparison options and drop target_metadata for MigrationContext.
        options = build_migration_context_options(target_metadata=Base.metadata)
        options.pop("target_metadata", None)
        context = MigrationContext.configure(connection=sync_connection, opts=options)
        diffs = compare_metadata(context, Base.metadata)
        return diffs

      # Run the comparison against the live connection in a sync context.
      return await connection.run_sync(_compare)

  finally:
    await engine.dispose()


def main() -> None:
  """Exit non-zero when drift exists and is not allowlisted."""
  try:
    # Execute drift detection in an isolated event loop.
    diffs = asyncio.run(_collect_drift())
  except RuntimeError as exc:
    print(f"ERROR: {exc}")
    sys.exit(1)

  # Filter diffs using an explicit allowlist when configured.
  allowlist = _load_allowlist()
  diffs = _filter_diffs(diffs, allowlist)

  # Report diffs so developers can see exactly what drift was detected.
  if diffs:
    print("Schema drift detected:")
    for diff in diffs:
      print(f"- {diff}")

    sys.exit(1)

  print("Schema drift check passed.")


if __name__ == "__main__":
  main()
