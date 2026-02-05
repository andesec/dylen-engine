"""Validate that Alembic migrations form a linear chain ordered by Create Date."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import timedelta
from pathlib import Path

from alembic.script import ScriptDirectory

# Ensure repo root is on sys.path so local imports work when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.migration_order import MigrationInfo, load_migration_chain, load_script_directory, rewrite_create_date


def _find_merge_revisions(script: ScriptDirectory) -> list[str]:
  """Return revision IDs that declare multiple down_revisions."""
  # Inspect all revisions for tuple/list down_revision values.
  merge_revisions: list[str] = []
  for revision in script.walk_revisions():
    down_revision = revision.down_revision
    if isinstance(down_revision, (tuple, list)):
      merge_revisions.append(str(revision.revision))

  return merge_revisions


def _check_create_date_order(chain: list[MigrationInfo]) -> list[str]:
  """Ensure Create Date timestamps are non-decreasing along the linear chain."""
  # Compare each revision with its predecessor to enforce chronological order.
  errors: list[str] = []
  for index in range(1, len(chain)):
    previous = chain[index - 1]
    current = chain[index]
    if previous.create_date <= current.create_date:
      continue

    # Report violations with a clear remediation.
    errors.append(f"Create Date ordering violation: {previous.revision} ({previous.create_date.isoformat()}) > {current.revision} ({current.create_date.isoformat()}). Edit down_revision to follow Create Date ordering.")

  return errors


def _fix_create_date_order(chain: list[MigrationInfo]) -> list[tuple[Path, str]]:
  """Adjust Create Date headers forward so the chain is monotonic."""
  # Track applied fixes so we can report deterministic updates.
  fixes: list[tuple[Path, str]] = []
  # Seed the last known Create Date from the base migration.
  last_seen = chain[0].create_date
  # Walk the chain to enforce non-decreasing Create Date values.
  for index in range(1, len(chain)):
    current = chain[index]
    # Skip when the Create Date already respects ordering.
    if current.create_date >= last_seen:
      last_seen = current.create_date
      continue

    # Bump the Create Date forward by one second to preserve order.
    new_date = last_seen + timedelta(seconds=1)
    # Mirror Alembic header formatting for clear reporting.
    formatted_value = new_date.replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")
    rewrite_create_date(path=current.path, create_date=new_date)
    fixes.append((current.path, formatted_value))
    last_seen = new_date

  return fixes


def main() -> None:
  """Run linear-history checks and exit non-zero on violations."""
  # Build the CLI parser so callers can request autofix behavior.
  parser = argparse.ArgumentParser(description="Validate Alembic linear history and Create Date ordering.")
  # Register the optional autofix flag for local workflows.
  parser.add_argument("--fix", action="store_true", help="Auto-fix Create Date ordering violations by bumping timestamps.")
  # Parse CLI args once so checks behave deterministically.
  args = parser.parse_args()
  # Respect opt-in autofix so CI stays read-only by default.
  fix_enabled = args.fix or os.getenv("MIGRATION_CREATE_DATE_AUTOFIX", "") == "1"
  # Load the script directory to inspect all revisions.
  script = load_script_directory()
  # Check for merge revisions explicitly.
  merge_revisions = _find_merge_revisions(script)
  if merge_revisions:
    print("ERROR: Merge revisions are not allowed.")
    print(f"Found merge revisions: {', '.join(merge_revisions)}")
    sys.exit(1)

  # Load the ordered migration chain from base to head.
  chain = load_migration_chain()
  # Enforce Create Date ordering along the linear chain.
  errors = _check_create_date_order(chain)
  if errors:
    if fix_enabled and chain:
      # Apply automatic fixes before failing to keep local workflows smooth.
      fixes = _fix_create_date_order(chain)
      if fixes:
        print("NOTICE: Auto-fixed Create Date ordering violations.")
        for path, new_value in fixes:
          print(f"- Updated {path} -> {new_value}")

        # Reload the chain after rewrites to re-check ordering.
        chain = load_migration_chain()
        errors = _check_create_date_order(chain)
        if not errors:
          head = chain[-1].revision
          print(f"OK: Linear migration chain verified after autofix (head={head}).")
          return

    print("ERROR: Create Date ordering checks failed.")
    for message in errors:
      print(f"- {message}")

    sys.exit(1)

  # Report success for CI visibility.
  if chain:
    head = chain[-1].revision
    print(f"OK: Linear migration chain verified (head={head}).")
  else:
    print("OK: No migrations detected.")


if __name__ == "__main__":
  main()
