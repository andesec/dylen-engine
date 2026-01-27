import argparse
import asyncio
import logging
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from os.path import abspath, dirname

# Add project root to path
BACKEND_DIR = dirname(dirname(abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import inspect, text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.core.database import get_db_engine  # noqa: E402
from scripts.init_db import create_database_if_not_exists  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("smart_migrate")

_EXPECTED_TABLES = {"users", "roles", "permissions", "role_permissions", "organizations"}
_EXPECTED_USER_COLUMNS = {"profession", "role_id", "org_id", "status", "auth_method"}


async def check_db_state() -> tuple[bool, set[str], set[str]]:
  """Inspect the DB to determine whether Alembic is already managing it."""
  engine = get_db_engine()
  try:
    async with engine.connect() as conn:

      def _inspect(sync_conn):  # type: ignore[no-untyped-def]
        inspector = inspect(sync_conn)
        tables = set(inspector.get_table_names())
        has_alembic = "alembic_version" in tables
        user_columns: set[str] = set()
        if "users" in tables:
          user_columns = {str(col.get("name")) for col in inspector.get_columns("users") if col.get("name")}

        return has_alembic, tables, user_columns

      return await conn.run_sync(_inspect)
  finally:
    await engine.dispose()


def run_command(cmd, check=True, cwd=None):
  logger.info(f"Running: {cmd}")
  if isinstance(cmd, str):
    cmd = shlex.split(cmd)
  try:
    result = subprocess.run(cmd, shell=False, check=check, capture_output=True, text=True, cwd=cwd)
    if result.stdout:
      logger.info(result.stdout.strip())
    if result.stderr:
      logger.warning(result.stderr.strip())
    return result.returncode
  except subprocess.CalledProcessError as e:
    logger.error(f"Command failed: {cmd}")
    if e.stdout:
      logger.error(e.stdout.strip())
    if e.stderr:
      logger.error(e.stderr.strip())
    raise e


def backup_db(settings: Settings):
  """Create a pre-migration backup of the database."""
  if not settings.pg_dsn:
    logger.warning("No DSN provided. Skipping backup.")
    return

  # Check if pg_dump is available
  if not shutil.which("pg_dump"):
    logger.critical("🛑 pg_dump NOT FOUND. Cannot perform pre-migration backup.")
    logger.critical("Install postgresql-client or ensure pg_dump is in PATH.")
    sys.exit(1)

  # Ensure backup directory exists
  os.makedirs(settings.backup_dir, exist_ok=True)

  timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
  filename = os.path.join(settings.backup_dir, f"pre_migration_{timestamp}.sql")

  logger.info(f"Creating pre-migration backup: {filename}")

  # Convert async DSN to pg_dump compatible URI (postgresql+asyncpg -> postgresql)
  uri = settings.pg_dsn.replace("+asyncpg", "")

  try:
    # Use -x to exclude privileges and -O to exclude ownership (safer for restores)
    # Use --no-owner --no-privileges for better portability
    run_command(f'pg_dump --dbname="{uri}" -f "{filename}" -x -O')
    logger.info("✅ Backup created successfully.")
  except Exception as e:
    logger.error(f"❌ Backup failed: {e}")
    logger.error("Migration aborted for safety.")
    sys.exit(1)


async def wait_for_db(retries=30, delay=2):
  logger.info("Waiting for database...")
  engine = get_db_engine()
  if engine is None:
    logger.critical("Database engine could not be initialized. Check DGS_PG_DSN environment variable.")
    raise RuntimeError("Database engine is None. DGS_PG_DSN is likely missing or empty.")

  for i in range(retries):
    try:
      async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
      logger.info("Database is ready.")
      return
    except (OperationalError, OSError) as e:
      if i == retries - 1:
        logger.error(f"Could not connect to database after {retries} attempts: {e}")
        raise e
      logger.info(f"Database not ready yet, retrying in {delay}s...")
      await asyncio.sleep(delay)
    finally:
      await engine.dispose()


async def main():
  parser = argparse.ArgumentParser(description="Smart Database Migrator")
  parser.add_argument("--force-sync-prod", action="store_true", help="Force auto-sync in production (DANGEROUS)")
  parser.add_argument("--backup", action="store_true", help="Force a pre-migration backup (even in Dev)")
  parser.add_argument("--skip-backup", action="store_true", help="Skip pre-migration backup (DANGEROUS in Prod)")
  args = parser.parse_args()

  settings = get_settings()
  app_env = settings.environment.lower() if settings.environment else "development"
  is_prod = app_env == "production"

  logger.info(f"Environment: {app_env}")

  # 1. Wait for DB
  await wait_for_db()

  # 2. Initialize DB (Create if missing)
  logger.info("Ensuring database exists...")
  await create_database_if_not_exists()

  # 3. Handle Backup
  should_backup = (is_prod or args.backup) and not args.skip_backup
  if should_backup:
    backup_db(settings)

  # Check DB state for legacy support (RBAC logic)
  logger.info("Checking database state for legacy compatibility...")
  try:
    has_alembic, tables, user_columns = await check_db_state()
    missing_tables = _EXPECTED_TABLES.difference(tables)
    missing_user_columns = _EXPECTED_USER_COLUMNS.difference(user_columns)

    if not has_alembic and "users" in tables:
      logger.info("⚠️  Existing database detected WITHOUT Alembic history.")
      # Only stamp when the schema already includes the latest RBAC/user columns.

      if not missing_tables and not missing_user_columns:
        logger.info("   -> Expected RBAC tables/columns present; stamping database as 'head'...")
        run_command([sys.executable, "-m", "alembic", "stamp", "heads"])
      else:
        logger.info("   -> Missing tables: %s", ", ".join(sorted(missing_tables)) if missing_tables else "(none)")
        logger.info("   -> Missing user columns: %s", ", ".join(sorted(missing_user_columns)) if missing_user_columns else "(none)")
        logger.info("   -> Skipping stamp; will apply migrations to add missing structures.")
  except Exception as e:
    logger.warning(f"Failed to check legacy DB state (non-critical): {e}")

  # 4. Apply existing migrations
  logger.info("Applying existing migrations...")
  try:
    # First, check if the current revision is valid
    try:
      run_command("python -m alembic current", cwd=BACKEND_DIR)
    except subprocess.CalledProcessError as e:
      if "Can't locate revision identified by" in (e.stderr or ""):
        logger.warning(f"⚠️  Orphaned migration revision detected: {e.stderr.strip()}")
        if not missing_tables and not missing_user_columns:
          logger.info("   -> Schema appears in sync with RBAC; stamping as 'heads' to recover...")
          try:
            run_command("python -m alembic stamp heads", cwd=BACKEND_DIR)
          except subprocess.CalledProcessError as stamp_err:
            if "Can't locate revision identified by" in (stamp_err.stderr or ""):
              logger.warning("   -> Stamp failed due to bad revision in DB. Forcing cleanup of alembic_version table.")
              engine = get_db_engine()
              async with engine.begin() as conn:
                await conn.execute(text("DELETE FROM alembic_version"))
              await engine.dispose()
              logger.info("   -> alembic_version table cleared. Retrying stamp...")
              run_command("python -m alembic stamp heads", cwd=BACKEND_DIR)
            else:
              raise stamp_err
        else:
          logger.error("   -> Schema is NOT in sync and revision is missing. Manual intervention required.")
          sys.exit(1)
      else:
        raise e

    run_command("python -m alembic upgrade heads", cwd=BACKEND_DIR)
  except subprocess.CalledProcessError:
    # Check if multiple heads issue
    logger.warning("Upgrade failed. Checking for multiple heads...")
    try:
      run_command("python -m alembic merge heads -m 'merge_heads'", check=True, cwd=BACKEND_DIR)
      logger.info("Heads merged. Retrying upgrade...")
      run_command("python -m alembic upgrade heads", cwd=BACKEND_DIR)
    except subprocess.CalledProcessError:
      logger.error("Migration upgrade failed.")
      sys.exit(1)

  # 4. Check for Drift
  logger.info("Checking for schema drift...")
  drift_code = run_command("python -m alembic check", check=False, cwd=BACKEND_DIR)

  if drift_code == 0:
    logger.info("✅ Schema is in sync with code.")
    sys.exit(0)

  logger.warning("⚠️  Schema drift detected!")

  # 5. Handle Drift
  if is_prod and not args.force_sync_prod:
    logger.critical("🛑 CRITICAL: Database schema is out of sync in PRODUCTION.")
    logger.critical("Auto-sync is disabled to prevent data loss.")
    logger.critical("Run local migrations and commit the result, or use --force-sync-prod if absolutely sure.")
    sys.exit(1)

  logger.info("🔄 Auto-syncing schema (Dev mode or Forced)...")
  try:
    # Auto-generate migration
    run_command('python -m alembic revision --autogenerate -m "auto_sync_schema"', cwd=BACKEND_DIR)

    # Apply it
    run_command("python -m alembic upgrade heads", cwd=BACKEND_DIR)

    # Re-check drift to handle "Partial Sync" (e.g. blocked drops)
    logger.info("Verifying sync status...")
    drift_code_after = run_command("python -m alembic check", check=False, cwd=BACKEND_DIR)

    if drift_code_after == 0:
      logger.info("✅ Schema synced successfully.")
    else:
      logger.warning("⚠️  Partial sync complete. Schema drift persists.")
      logger.warning("   This usually means destructive changes (DROP TABLE/COLUMN) were blocked by safety rules.")
      logger.warning("   The application should function safely, but manual cleanup is required.")

  except subprocess.CalledProcessError:
    logger.error("Failed to auto-sync schema.")
    sys.exit(1)


if __name__ == "__main__":
  if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    sys.exit(130)
  except Exception as e:
    logger.error("Unexpected error: %s", e)
    sys.exit(1)


if __name__ == "__main__":
  if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    sys.exit(130)
  except Exception as e:
    logger.error("Unexpected error: %s", e)
    sys.exit(1)
