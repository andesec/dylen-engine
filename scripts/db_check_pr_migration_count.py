from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run_git(command: list[str]) -> str:
  """Execute git commands to inspect PR changes without external dependencies."""
  # Use git to read repo state without additional libraries.
  result = subprocess.run(command, check=True, capture_output=True, text=True)
  return result.stdout.strip()


def _resolve_base_ref() -> str:
  """Determine the base branch for PR diffs in CI or local runs."""
  # Prefer GitHub's base ref when running in CI.
  base_ref = os.getenv("GITHUB_BASE_REF", "")
  if base_ref:
    return base_ref

  # Fall back to main when no base ref is provided.
  return "main"


def _changed_files(base_ref: str) -> list[str]:
  """Collect changed files between base ref and HEAD."""
  # Resolve repository root so git commands run from a stable directory.
  repo_root = Path(__file__).resolve().parents[1]
  command = ["git", "-C", str(repo_root), "diff", "--name-only", f"origin/{base_ref}...HEAD"]
  output = _run_git(command)
  if not output:
    return []

  return [line.strip() for line in output.splitlines() if line.strip()]


def _schema_changes(files: list[str]) -> bool:
  """Check whether SQLAlchemy schema files were modified."""
  # Treat any changes under app/schema as schema-impacting.
  return any(path.startswith("dgs-backend/app/schema/") for path in files)


def _migration_changes(files: list[str]) -> list[str]:
  """Return migration file paths changed in the PR diff."""
  # Limit to versioned migration scripts.
  return [path for path in files if path.startswith("dgs-backend/alembic/versions/") and path.endswith(".py")]


def main() -> None:
  """Enforce the one-migration-per-PR rule when schema files change."""
  # Resolve the base ref so diffs match the PR target.
  base_ref = _resolve_base_ref()
  # Collect changed files from the base ref to HEAD.
  files = _changed_files(base_ref)
  # Detect whether schema files changed and which migrations were added.
  schema_changed = _schema_changes(files)
  migration_files = _migration_changes(files)

  # Only enforce the rule when schema files changed in the PR.
  if schema_changed and len(migration_files) != 1:
    print("ERROR: Schema changes detected without exactly one migration file.")
    print(f"Found migration files: {migration_files if migration_files else 'none'}")
    print("Remediation: add exactly one migration file or split schema changes into multiple PRs.")
    sys.exit(1)

  print("OK: One-migration-per-PR check passed.")


if __name__ == "__main__":
  main()
