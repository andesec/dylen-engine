import argparse
import asyncio
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from os.path import abspath, dirname

# Add project root to path
BACKEND_DIR = dirname(dirname(abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.core.database import get_db_engine  # noqa: E402
from scripts.init_db import create_database_if_not_exists  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("smart_migrate")


def run_command(cmd, check=True, cwd=None):
  logger.info(f"Running: {cmd}")
  try:
    result = subprocess.run(cmd, shell=True, check=check, capture_output=True, text=True, cwd=cwd)
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

  # 4. Apply existing migrations
  logger.info("Applying existing migrations...")
  try:
    run_command("python -m alembic upgrade head", cwd=BACKEND_DIR)
  except subprocess.CalledProcessError:
    # Check if multiple heads issue
    logger.warning("Upgrade failed. Checking for multiple heads...")
    try:
      run_command("python -m alembic merge heads -m 'merge_heads'", check=True, cwd=BACKEND_DIR)
      logger.info("Heads merged. Retrying upgrade...")
      run_command("python -m alembic upgrade head", cwd=BACKEND_DIR)
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
    run_command("python -m alembic upgrade head", cwd=BACKEND_DIR)

    # Re-check drift to handle "Partial Sync" (e.g. blocked drops)
    logger.info("Verifying sync status...")
    drift_code_after = run_command("uv run alembic check", check=False, cwd=BACKEND_DIR)

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
    logger.error(f"Unexpected error: {e}")
    sys.exit(1)
