from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path


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


def _replace_once(text: str, needle: str, replacement: str) -> str:
  """Replace a substring exactly once so patching fails loudly when structure changes."""
  if text.count(needle) != 1:
    raise RuntimeError(f"Expected to find exactly one occurrence of {needle!r}.")

  return text.replace(needle, replacement, 1)


def _patch_baseline_for_seed_data(*, path: Path) -> None:
  """Inject idempotent seed data into the freshly generated baseline migration."""
  text = path.read_text(encoding="utf-8")
  if "Seed required reference data" in text:
    return

  # Ensure future annotations are enabled so we can use modern typing without syntax issues.
  if "from __future__ import annotations" not in text:
    text = "from __future__ import annotations\n\n" + text

  # Inject required imports for seed inserts.
  if "import uuid" not in text:
    text = _replace_once(text, "from alembic import op\n", "from alembic import op\nimport uuid\n")

  if "from sqlalchemy.dialects.postgresql import insert" not in text:
    text = _replace_once(text, "from sqlalchemy.dialects import postgresql\n", "from sqlalchemy.dialects import postgresql\nfrom sqlalchemy.dialects.postgresql import insert\n")

  seed_block = (
    "    # Seed required reference data so auth/quota code paths never 500 on a fresh DB.\n"
    "    # Use fixed UUIDs so environments stay consistent after local resets.\n"
    '    role_super_admin_id = uuid.UUID("3e56ebfc-1d62-42cb-a920-ab6e916e58bf")\n'
    '    role_org_admin_id = uuid.UUID("102d6fab-322c-48f8-a8f8-0d9e5eb52aa6")\n'
    '    role_org_member_id = uuid.UUID("d028adea-31a6-48fb-afd8-777a4cd410b4")\n'
    '    permission_user_manage_id = uuid.UUID("2fcaeb8d-9824-4506-953a-c5e949db3db8")\n'
    '    roles_table = sa.table("roles", sa.column("id"), sa.column("name"), sa.column("level"), sa.column("description"))\n'
    '    permissions_table = sa.table("permissions", sa.column("id"), sa.column("slug"), sa.column("display_name"), sa.column("description"))\n'
    '    role_permissions_table = sa.table("role_permissions", sa.column("role_id"), sa.column("permission_id"))\n'
    "    subscription_tiers_table = sa.table(\n"
    '        "subscription_tiers",\n'
    '        sa.column("name"),\n'
    '        sa.column("max_file_upload_kb"),\n'
    '        sa.column("highest_lesson_depth"),\n'
    '        sa.column("max_sections_per_lesson"),\n'
    '        sa.column("file_upload_quota"),\n'
    '        sa.column("image_upload_quota"),\n'
    '        sa.column("gen_sections_quota"),\n'
    '        sa.column("research_quota"),\n'
    '        sa.column("coach_mode_enabled"),\n'
    '        sa.column("coach_voice_tier"),\n'
    "    )\n"
    "    op.execute(\n"
    "        insert(roles_table)\n"
    "        .values(\n"
    "            [\n"
    '                {"id": role_super_admin_id, "name": "Super Admin", "level": "GLOBAL", "description": "Global administrator."},\n'
    '                {"id": role_org_admin_id, "name": "Org Admin", "level": "TENANT", "description": "Organization administrator."},\n'
    '                {"id": role_org_member_id, "name": "Org Member", "level": "TENANT", "description": "Default role for new users."},\n'
    "            ]\n"
    "        )\n"
    '        .on_conflict_do_nothing(index_elements=["name"])\n'
    "    )\n"
    "    op.execute(\n"
    "        insert(permissions_table)\n"
    "        .values(\n"
    "            [\n"
    "                {\n"
    '                    "id": permission_user_manage_id,\n'
    '                    "slug": "user:manage",\n'
    '                    "display_name": "Manage Users",\n'
    '                    "description": "List users and update roles/statuses.",\n'
    "                }\n"
    "            ]\n"
    "        )\n"
    '        .on_conflict_do_nothing(index_elements=["slug"])\n'
    "    )\n"
    "    op.execute(\n"
    "        insert(role_permissions_table)\n"
    '        .values([{"role_id": role_super_admin_id, "permission_id": permission_user_manage_id}])\n'
    '        .on_conflict_do_nothing(index_elements=["role_id", "permission_id"])\n'
    "    )\n"
    "    op.execute(\n"
    "        insert(subscription_tiers_table)\n"
    "        .values(\n"
    "            [\n"
    "                {\n"
    '                    "name": "Free",\n'
    '                    "max_file_upload_kb": 512,\n'
    '                    "highest_lesson_depth": "highlights",\n'
    '                    "max_sections_per_lesson": 2,\n'
    '                    "file_upload_quota": 0,\n'
    '                    "image_upload_quota": 0,\n'
    '                    "gen_sections_quota": 20,\n'
    '                    "research_quota": None,\n'
    '                    "coach_mode_enabled": False,\n'
    '                    "coach_voice_tier": "none",\n'
    "                },\n"
    "                {\n"
    '                    "name": "Plus",\n'
    '                    "max_file_upload_kb": 1024,\n'
    '                    "highest_lesson_depth": "detailed",\n'
    '                    "max_sections_per_lesson": 6,\n'
    '                    "file_upload_quota": 5,\n'
    '                    "image_upload_quota": 5,\n'
    '                    "gen_sections_quota": 100,\n'
    '                    "research_quota": None,\n'
    '                    "coach_mode_enabled": True,\n'
    '                    "coach_voice_tier": "device",\n'
    "                },\n"
    "                {\n"
    '                    "name": "Pro",\n'
    '                    "max_file_upload_kb": 2048,\n'
    '                    "highest_lesson_depth": "training",\n'
    '                    "max_sections_per_lesson": 10,\n'
    '                    "file_upload_quota": 10,\n'
    '                    "image_upload_quota": 10,\n'
    '                    "gen_sections_quota": 250,\n'
    '                    "research_quota": None,\n'
    '                    "coach_mode_enabled": True,\n'
    '                    "coach_voice_tier": "premium",\n'
    "                },\n"
    "            ]\n"
    "        )\n"
    '        .on_conflict_do_nothing(index_elements=["name"])\n'
    "    )\n"
  )

  text = _replace_once(text, "    # ### end Alembic commands ###\n", seed_block + "    # ### end Alembic commands ###\n")
  path.write_text(text, encoding="utf-8")


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
  parser.add_argument("--app-dir", default="dylen-engine")
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
  _patch_baseline_for_seed_data(path=baseline_path)

  # Apply the baseline migration so the local DB is ready for development.
  _run(["uv", "run", "alembic", "-c", str(app_dir / "alembic.ini"), "upgrade", "head"], env=env)
  print(f"OK: Regenerated baseline migration at {baseline_path}")


if __name__ == "__main__":
  main()
