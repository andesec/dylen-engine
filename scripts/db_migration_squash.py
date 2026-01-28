from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine


def _repo_root() -> Path:
  """Resolve the repository root so paths remain stable from any working directory."""
  return Path(__file__).resolve().parents[1]


def _require_env(name: str) -> str:
  """Read required environment variables to prevent accidental DB targeting."""
  value = os.getenv(name, "").strip()
  if not value:
    raise RuntimeError(f"{name} is required (set it in your shell or .env).")

  return value


def _run_git(command: list[str]) -> str:
  """Execute a git command and return stdout for merge-base computations."""
  result = subprocess.run(command, check=True, capture_output=True, text=True, cwd=_repo_root())
  return result.stdout.strip()


def _merge_base(*, base_ref: str) -> str:
  """Resolve the merge base with origin/<base_ref> so squashes match the PR base."""
  # Prefer origin/<base_ref> so local branches don't drift from the PR base.
  base_target = f"origin/{base_ref}"
  try:
    _run_git(["git", "rev-parse", "--verify", base_target])
    return _run_git(["git", "merge-base", "HEAD", base_target])
  except subprocess.CalledProcessError as exc:
    raise RuntimeError(f"Unable to compute merge base vs {base_target}. Run: git fetch origin {base_ref}") from exc


def _migration_paths_at_ref(*, ref: str) -> list[str]:
  """List migration version file paths at a given git ref."""
  # Use git ls-tree so we can read the previous migration graph without checking it out.
  output = _run_git(["git", "ls-tree", "-r", "--name-only", ref, "dylen-engine/alembic/versions"])
  if not output:
    return []

  return [line.strip() for line in output.splitlines() if line.strip().endswith(".py")]


def _read_file_at_ref(*, ref: str, path: str) -> str:
  """Read a file from a git ref without mutating the working tree."""
  return _run_git(["git", "show", f"{ref}:{path}"])


def _parse_revision_file(*, text_content: str) -> tuple[str | None, list[str]]:
  """Extract revision and down_revision ids from a migration file without executing it."""
  # Parse revision identifiers via regex to keep the script dependency-free.
  revision_match = re.search(r'^\s*revision\s*:\s*str\s*=\s*"([^"]+)"\s*$', text_content, flags=re.MULTILINE)
  down_match = re.search(r"^\s*down_revision\s*:\s*.*=\s*(.+?)\s*$", text_content, flags=re.MULTILINE)
  revision = revision_match.group(1) if revision_match else None
  down_revisions: list[str] = []
  if down_match:
    # Extract all string literals from the RHS to cover both "abc" and ("a", "b") styles.
    down_revisions = re.findall(r'"([^"]+)"', down_match.group(1))

  return revision, down_revisions


def _head_revision_at_ref(*, ref: str) -> str:
  """Compute the Alembic head at a ref by analyzing revision dependencies."""
  paths = _migration_paths_at_ref(ref=ref)
  revisions: set[str] = set()
  referenced: set[str] = set()
  for path in paths:
    file_text = _read_file_at_ref(ref=ref, path=path)
    revision, down_revisions = _parse_revision_file(text_content=file_text)
    if revision:
      revisions.add(revision)

    referenced.update([parent for parent in down_revisions if parent])

  # Heads are revisions that are not referenced as a parent by any other revision.
  heads = sorted([rev for rev in revisions if rev not in referenced])
  if len(heads) != 1:
    raise RuntimeError(f"Expected exactly one head at {ref}, found: {heads if heads else 'none'}")

  return heads[0]


def _backup_extra_migrations(*, merge_base_ref: str, versions_dir: Path) -> list[Path]:
  """Move non-merge-base migrations into a local backup folder to enable squashing."""
  keep_paths = {Path(path).name for path in _migration_paths_at_ref(ref=merge_base_ref)}
  backup_dir = versions_dir / ".squash_backup" / str(int(time.time()))
  moved: list[Path] = []
  for path in sorted(versions_dir.glob("*.py")):
    # Keep migrations that existed on the PR base so the chain remains valid.
    if path.name in keep_paths:
      continue

    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / path.name
    path.rename(destination)
    moved.append(destination)

  return moved


def _build_temp_database_url(dsn: str, *, label: str) -> tuple[str, str, str]:
  """Create a temp database URL and admin URL for isolated autogenerate runs."""
  base_url = make_url(dsn)
  base_name = base_url.database or "postgres"
  suffix = int(time.time() * 1000)
  temp_db_name = f"{base_name}_{label}_{suffix}"
  admin_url = base_url.set(database="postgres")
  temp_url = base_url.set(database=temp_db_name)
  return str(temp_url), str(admin_url), temp_db_name


def _create_database(admin_url: str, db_name: str) -> None:
  """Create a temporary database for squashed migration autogeneration."""

  async def _create() -> None:
    """Create the database via a short-lived async engine."""
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
      async with engine.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{db_name}"'))

    finally:
      await engine.dispose()

  asyncio.run(_create())


def _drop_database(admin_url: str, db_name: str) -> None:
  """Drop the temporary database after autogenerate completes."""

  async def _drop() -> None:
    """Drop the database via a short-lived async engine."""
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
      async with engine.connect() as connection:
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))

    finally:
      await engine.dispose()

  asyncio.run(_drop())


def _run(command: list[str], *, env: dict[str, str]) -> None:
  """Run a command from repo root so relative paths resolve consistently."""
  subprocess.run(command, check=True, cwd=_repo_root(), env=env)


def main() -> None:
  """Squash multiple local migrations into a single migration based on the PR merge base."""
  parser = argparse.ArgumentParser(description="Squash local migration revisions into one (local dev helper).")
  parser.add_argument("--message", required=True, help="Migration message, e.g. 'squash_schema_changes'.")
  parser.add_argument("--base-ref", default="main", help="Base branch for merge-base calculations (default: main).")
  parser.add_argument("--yes", action="store_true", help="Acknowledge that local migration files will be moved to a backup folder.")
  args = parser.parse_args()

  if not args.yes:
    print("ERROR: Refusing to modify migration files without --yes.")
    print("This command moves non-base migrations into dylen-engine/alembic/versions/.squash_backup/.")
    sys.exit(1)

  # Require env vars explicitly so Alembic doesn't target a default database implicitly.
  dsn = _require_env("DYLEN_PG_DSN")
  _require_env("DYLEN_ALLOWED_ORIGINS")
  repo_root = _repo_root()
  alembic_ini = repo_root / "dylen-engine" / "alembic.ini"
  versions_dir = repo_root / "dylen-engine" / "alembic" / "versions"
  env = os.environ.copy()
  env["PYTHONPATH"] = str(repo_root / "dylen-engine") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

  # Compute merge base and identify the PR base migration head.
  merge_base_ref = _merge_base(base_ref=args.base_ref)
  base_head = _head_revision_at_ref(ref=merge_base_ref)
  print(f"Merge base: {merge_base_ref}")
  print(f"Base Alembic head: {base_head}")

  # Backup local-only migrations so Alembic head matches the PR base again.
  moved = _backup_extra_migrations(merge_base_ref=merge_base_ref, versions_dir=versions_dir)
  if moved:
    print(f"Backed up {len(moved)} local migration(s) into .squash_backup/.")
  else:
    print("No extra local migrations found to squash; continuing.")

  # Use an isolated DB at base schema so autogenerate produces one combined diff.
  temp_url, admin_url, temp_name = _build_temp_database_url(dsn, label="squash")
  _create_database(admin_url, temp_name)
  env["DYLEN_PG_DSN"] = temp_url
  try:
    _run([sys.executable, "-m", "alembic", "-c", str(alembic_ini), "upgrade", "head"], env=env)
    _run([sys.executable, "-m", "alembic", "-c", str(alembic_ini), "revision", "--autogenerate", "-m", args.message], env=env)
    _run([sys.executable, "scripts/db_migration_lint.py"], env=env)
    _run([sys.executable, "scripts/db_check_heads.py"], env=env)

  finally:
    _drop_database(admin_url, temp_name)

  # Restore env so follow-up commands use the developer's configured DSN again.
  env["DYLEN_PG_DSN"] = dsn
  print("OK: Squashed migration generated.")
  print("NOTE: If you previously applied the backed-up migrations to your dev DB, recreate it before running make migrate.")


if __name__ == "__main__":
  main()
