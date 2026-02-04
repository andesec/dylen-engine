"""Validate that Alembic migrations form a linear chain ordered by Create Date."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.script import ScriptDirectory

# Ensure repo root is on sys.path so local imports work when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.migration_order import MigrationInfo, load_migration_chain, load_script_directory


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


def main() -> None:
  """Run linear-history checks and exit non-zero on violations."""
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
