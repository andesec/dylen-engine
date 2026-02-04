from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Ensure repo root is on sys.path so local imports work when invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.db_migration_guard import guard_migration_file


def _repo_root() -> Path:
  """Resolve the repository root so all paths are stable regardless of cwd."""
  return Path(__file__).resolve().parents[1]


def _run(command: list[str], *, env: dict[str, str]) -> None:
  """Run commands from repo root so relative paths behave deterministically."""
  subprocess.run(command, check=True, cwd=_repo_root(), env=env)


def _wait_for_postgres(*, env: dict[str, str], timeout_seconds: int) -> None:
  """Wait for the docker-compose postgres service to accept connections."""
  started_at = time.monotonic()
  while True:
    result = subprocess.run(["docker-compose", "exec", "-T", "postgres", "pg_isready", "-U", "dylen", "-d", "dylen"], cwd=_repo_root(), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
      return

    if time.monotonic() - started_at > timeout_seconds:
      raise RuntimeError("Timed out waiting for Postgres to become ready.")

    time.sleep(2)


def _require_confirmation() -> None:
  """Block destructive operations unless the caller explicitly opts in."""
  if os.getenv("CONFIRM_DB_NUKE", "") != "1":
    raise RuntimeError("Refusing to nuke DB/migrations without CONFIRM_DB_NUKE=1.")


def _latest_migration_file(*, versions_dir: Path) -> Path:
  """Return the most recently modified migration file so we can patch it."""
  candidates = [path for path in versions_dir.glob("*.py") if path.is_file()]
  if not candidates:
    raise RuntimeError(f"No migration files were generated in {versions_dir}.")

  return max(candidates, key=lambda path: path.stat().st_mtime)


def _extract_revision_id(*, path: Path) -> str:
  """Extract the Alembic revision id from the migration file."""
  # Parse the revision id from the Alembic header to name the seed script.
  text = path.read_text(encoding="utf-8")
  match = re.search(r"^Revision ID:\s*(?P<rev>[0-9a-f]+)\s*$", text, re.MULTILINE)
  if not match:
    raise RuntimeError(f"Unable to parse Revision ID from {path}.")

  return match.group("rev")


def _seed_script_content(*, revision: str) -> str:
  """Return the default seed script content for a baseline revision."""
  # Embed a reference to the revision so the script is traceable.
  return (
    f'"""Seed core RBAC and subscription tiers for the baseline migration ({revision})."""\n\n'
    "from __future__ import annotations\n\n"
    "import uuid\n\n"
    "from sqlalchemy import text\n"
    "from sqlalchemy.ext.asyncio import AsyncConnection\n\n"
    "\n"
    "async def _table_exists(connection: AsyncConnection, *, table_name: str, schema: str | None = None) -> bool:\n"
    '  """Return True when a table exists in the target schema."""\n'
    "  # Default to public schema when none is provided.\n"
    '  resolved_schema = schema or "public"\n'
    "  # Query information_schema to detect table presence.\n"
    "  statement = text(\n"
    '    """\n'
    "    SELECT 1\n"
    "    FROM information_schema.tables\n"
    "    WHERE table_schema = :schema\n"
    "      AND table_name = :table_name\n"
    "      AND table_type = 'BASE TABLE'\n"
    "    LIMIT 1\n"
    '    """\n'
    "  )\n"
    '  result = await connection.execute(statement, {"schema": resolved_schema, "table_name": table_name})\n'
    "  return result.first() is not None\n\n"
    "async def _column_exists(connection: AsyncConnection, *, table_name: str, column_name: str, schema: str | None = None) -> bool:\n"
    '  """Return True when a column exists on the specified table."""\n'
    "  # Default to public schema when none is provided.\n"
    '  resolved_schema = schema or "public"\n'
    "  # Query information_schema to detect column presence.\n"
    "  statement = text(\n"
    '    """\n'
    "    SELECT 1\n"
    "    FROM information_schema.columns\n"
    "    WHERE table_schema = :schema\n"
    "      AND table_name = :table_name\n"
    "      AND column_name = :column_name\n"
    "    LIMIT 1\n"
    '    """\n'
    "  )\n"
    "  result = await connection.execute(\n"
    "    statement,\n"
    '    {"schema": resolved_schema, "table_name": table_name, "column_name": column_name},\n'
    "  )\n"
    "  return result.first() is not None\n\n"
    "async def _ensure_columns(connection: AsyncConnection, *, table_name: str, columns: list[str]) -> bool:\n"
    '  """Return True when all required columns exist on the table."""\n'
    "  # Ensure the table exists before checking columns.\n"
    "  if not await _table_exists(connection, table_name=table_name):\n"
    "    return False\n\n"
    "  # Confirm each required column exists before running DML.\n"
    "  for column in columns:\n"
    "    if not await _column_exists(connection, table_name=table_name, column_name=column):\n"
    "      return False\n\n"
    "  return True\n\n"
    "async def seed(connection: AsyncConnection) -> None:\n"
    '  """Insert required RBAC roles, permissions, and subscription tiers."""\n'
    "  # Use fixed UUIDs so environments stay consistent after local resets.\n"
    '  role_super_admin_id = uuid.UUID("3e56ebfc-1d62-42cb-a920-ab6e916e58bf")\n'
    '  role_org_admin_id = uuid.UUID("102d6fab-322c-48f8-a8f8-0d9e5eb52aa6")\n'
    '  role_org_member_id = uuid.UUID("d028adea-31a6-48fb-afd8-777a4cd410b4")\n'
    '  permission_user_manage_id = uuid.UUID("2fcaeb8d-9824-4506-953a-c5e949db3db8")\n\n'
    "  # Seed roles when the table and required columns exist.\n"
    '  if await _ensure_columns(connection, table_name="roles", columns=["id", "name", "level", "description"]):\n'
    "    await connection.execute(\n"
    "      text(\n"
    '        """\n'
    "        INSERT INTO roles (id, name, level, description)\n"
    "        VALUES\n"
    "          (:id1, :name1, :level1, :desc1),\n"
    "          (:id2, :name2, :level2, :desc2),\n"
    "          (:id3, :name3, :level3, :desc3)\n"
    "        ON CONFLICT (name) DO UPDATE\n"
    "        SET level = EXCLUDED.level,\n"
    "            description = EXCLUDED.description\n"
    '        """\n'
    "      ),\n"
    "      {\n"
    '        "id1": role_super_admin_id,\n'
    '        "name1": "Super Admin",\n'
    '        "level1": "GLOBAL",\n'
    '        "desc1": "Global administrator.",\n'
    '        "id2": role_org_admin_id,\n'
    '        "name2": "Org Admin",\n'
    '        "level2": "TENANT",\n'
    '        "desc2": "Organization administrator.",\n'
    '        "id3": role_org_member_id,\n'
    '        "name3": "Org Member",\n'
    '        "level3": "TENANT",\n'
    '        "desc3": "Default role for new users.",\n'
    "      },\n"
    "    )\n\n"
    "  # Seed permissions when the table and required columns exist.\n"
    '  if await _ensure_columns(connection, table_name="permissions", columns=["id", "slug", "display_name", "description"]):\n'
    "    await connection.execute(\n"
    "      text(\n"
    '        """\n'
    "        INSERT INTO permissions (id, slug, display_name, description)\n"
    "        VALUES (:id, :slug, :display_name, :description)\n"
    "        ON CONFLICT (slug) DO UPDATE\n"
    "        SET display_name = EXCLUDED.display_name,\n"
    "            description = EXCLUDED.description\n"
    '        """\n'
    "      ),\n"
    "      {\n"
    '        "id": permission_user_manage_id,\n'
    '        "slug": "user:manage",\n'
    '        "display_name": "Manage Users",\n'
    '        "description": "List users and update roles/statuses.",\n'
    "      },\n"
    "    )\n\n"
    "  # Seed role-permission mapping when the table and required columns exist.\n"
    '  if await _ensure_columns(connection, table_name="role_permissions", columns=["role_id", "permission_id"]):\n'
    "    await connection.execute(\n"
    "      text(\n"
    '        """\n'
    "        INSERT INTO role_permissions (role_id, permission_id)\n"
    "        VALUES (:role_id, :permission_id)\n"
    "        ON CONFLICT (role_id, permission_id) DO NOTHING\n"
    '        """\n'
    "      ),\n"
    "      {\n"
    '        "role_id": role_super_admin_id,\n'
    '        "permission_id": permission_user_manage_id,\n'
    "      },\n"
    "    )\n\n"
    "  # Seed subscription tiers when the table and required columns exist.\n"
    "  if await _ensure_columns(\n"
    "    connection,\n"
    '    table_name="subscription_tiers",\n'
    "    columns=[\n"
    '      "name",\n'
    '      "max_file_upload_kb",\n'
    '      "highest_lesson_depth",\n'
    '      "max_sections_per_lesson",\n'
    '      "file_upload_quota",\n'
    '      "image_upload_quota",\n'
    '      "gen_sections_quota",\n'
    '      "research_quota",\n'
    '      "coach_mode_enabled",\n'
    '      "coach_voice_tier",\n'
    "    ],\n"
    "  ):\n"
    "    await connection.execute(\n"
    "      text(\n"
    '        """\n'
    "        INSERT INTO subscription_tiers (\n"
    "          name,\n"
    "          max_file_upload_kb,\n"
    "          highest_lesson_depth,\n"
    "          max_sections_per_lesson,\n"
    "          file_upload_quota,\n"
    "          image_upload_quota,\n"
    "          gen_sections_quota,\n"
    "          research_quota,\n"
    "          coach_mode_enabled,\n"
    "          coach_voice_tier\n"
    "        )\n"
    "        VALUES\n"
    "          (:name1, :mfu1, :depth1, :sections1, :fuq1, :iuq1, :gsq1, :rq1, :coach1, :voice1),\n"
    "          (:name2, :mfu2, :depth2, :sections2, :fuq2, :iuq2, :gsq2, :rq2, :coach2, :voice2),\n"
    "          (:name3, :mfu3, :depth3, :sections3, :fuq3, :iuq3, :gsq3, :rq3, :coach3, :voice3)\n"
    "        ON CONFLICT (name) DO UPDATE\n"
    "        SET max_file_upload_kb = EXCLUDED.max_file_upload_kb,\n"
    "            highest_lesson_depth = EXCLUDED.highest_lesson_depth,\n"
    "            max_sections_per_lesson = EXCLUDED.max_sections_per_lesson,\n"
    "            file_upload_quota = EXCLUDED.file_upload_quota,\n"
    "            image_upload_quota = EXCLUDED.image_upload_quota,\n"
    "            gen_sections_quota = EXCLUDED.gen_sections_quota,\n"
    "            research_quota = EXCLUDED.research_quota,\n"
    "            coach_mode_enabled = EXCLUDED.coach_mode_enabled,\n"
    "            coach_voice_tier = EXCLUDED.coach_voice_tier\n"
    '        """\n'
    "      ),\n"
    "      {\n"
    '        "name1": "Free",\n'
    '        "mfu1": 512,\n'
    '        "depth1": "highlights",\n'
    '        "sections1": 2,\n'
    '        "fuq1": 0,\n'
    '        "iuq1": 0,\n'
    '        "gsq1": 20,\n'
    '        "rq1": None,\n'
    '        "coach1": False,\n'
    '        "voice1": "none",\n'
    '        "name2": "Plus",\n'
    '        "mfu2": 1024,\n'
    '        "depth2": "detailed",\n'
    '        "sections2": 6,\n'
    '        "fuq2": 5,\n'
    '        "iuq2": 5,\n'
    '        "gsq2": 100,\n'
    '        "rq2": None,\n'
    '        "coach2": True,\n'
    '        "voice2": "device",\n'
    '        "name3": "Pro",\n'
    '        "mfu3": 2048,\n'
    '        "depth3": "training",\n'
    '        "sections3": 10,\n'
    '        "fuq3": 10,\n'
    '        "iuq3": 10,\n'
    '        "gsq3": 250,\n'
    '        "rq3": None,\n'
    '        "coach3": True,\n'
    '        "voice3": "premium",\n'
    "      },\n"
    "    )\n"
  )


def _ensure_seed_script(*, revision: str, path: Path) -> None:
  """Create a seed script for the revision if it does not exist."""
  # Avoid overwriting existing seed scripts to preserve manual edits.
  if path.exists():
    return

  # Ensure the seed scripts directory exists before writing.
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(_seed_script_content(revision=revision), encoding="utf-8")


def _nuke_migrations(*, versions_dir: Path) -> None:
  """Delete all migration files so Alembic can rebuild a clean baseline."""
  for path in versions_dir.glob("*.py"):
    path.unlink()

  pycache_dir = versions_dir / "__pycache__"
  if pycache_dir.exists():
    for path in pycache_dir.rglob("*"):
      if path.is_file():
        path.unlink()

    for path in sorted(pycache_dir.rglob("*"), reverse=True):
      if path.is_dir():
        path.rmdir()

    pycache_dir.rmdir()


def main() -> None:
  """Nuke the local DB + Alembic versions and rebuild a baseline migration from models."""
  parser = argparse.ArgumentParser(description="Nuke local DB + migrations and regenerate a baseline migration from code.")
  parser.add_argument("--app-dir", default=".")
  parser.add_argument("--message", default="baseline")
  args = parser.parse_args()

  _require_confirmation()
  repo_root = _repo_root()
  app_dir = repo_root / args.app_dir
  versions_dir = app_dir / "alembic" / "versions"
  versions_dir.mkdir(parents=True, exist_ok=True)
  env = os.environ.copy()
  env.setdefault("DYLEN_PG_DSN", "postgresql://dylen:dylen_password@localhost:5432/dylen")
  env.setdefault("DYLEN_ALLOWED_ORIGINS", "http://localhost:3000")

  # Nuke the local docker DB volume and recreate a clean DB instance.
  _run(["docker-compose", "down", "-v"], env=env)
  _run(["docker-compose", "up", "-d", "postgres"], env=env)
  _wait_for_postgres(env=env, timeout_seconds=60)
  _run(["docker-compose", "run", "--rm", "postgres-init"], env=env)

  # Reset the migration history on disk.
  _nuke_migrations(versions_dir=versions_dir)

  # Autogenerate a baseline from the current ORM model state.
  _run(["uv", "run", "alembic", "-c", str(app_dir / "alembic.ini"), "revision", "--autogenerate", "-m", args.message], env=env)
  baseline_path = _latest_migration_file(versions_dir=versions_dir)
  # Guard DDL operations so the baseline is idempotent.
  guard_migration_file(path=baseline_path)
  # Create a seed script for the baseline revision if missing.
  revision_id = _extract_revision_id(path=baseline_path)
  seed_path = repo_root / "scripts" / "seeds" / f"{revision_id}.py"
  _ensure_seed_script(revision=revision_id, path=seed_path)

  # Apply the baseline migration so the local DB is ready for development.
  _run(["uv", "run", "alembic", "-c", str(app_dir / "alembic.ini"), "upgrade", "head"], env=env)
  print(f"OK: Regenerated baseline migration at {baseline_path}")


if __name__ == "__main__":
  main()
