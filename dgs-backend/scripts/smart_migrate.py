"""Apply Alembic migrations safely across managed and legacy databases.

How and why:
- This script supports "zero-touch" environments where a database might already
  have tables created outside Alembic (ex: early prototypes or `create_all`).
- Stamping a database as "head" is only safe when the schema already matches
  the current expected shape; otherwise it would hide missing migrations.
"""

import asyncio
import logging
import subprocess
import sys
from os.path import abspath, dirname

# Add project root to path
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from sqlalchemy import inspect  # noqa: E402

from app.core.database import get_db_engine  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
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


def run_command(argv: list[str]) -> None:
  """Run a subprocess command and exit with the same error code on failure."""
  logger.info("Running command: %s", " ".join(argv))
  try:
    subprocess.run(argv, check=True)
  except subprocess.CalledProcessError as e:
    logger.error("Command failed with exit code %s: %s", e.returncode, " ".join(argv))
    sys.exit(e.returncode)


async def main() -> None:
  """Detect legacy DBs, stamp when safe, then apply migrations."""
  logger.info("Checking database state...")
  try:
    has_alembic, tables, user_columns = await check_db_state()
  except Exception as e:
    logger.error("Failed to connect to database: %s", e)
    sys.exit(1)

  if has_alembic:
    logger.info("✅ Database is already managed by Alembic.")

  elif "users" in tables:
    logger.info("⚠️  Existing database detected WITHOUT Alembic history.")
    # Only stamp when the schema already includes the latest RBAC/user columns.
    missing_tables = _EXPECTED_TABLES.difference(tables)
    missing_user_columns = _EXPECTED_USER_COLUMNS.difference(user_columns)

    if not missing_tables and not missing_user_columns:
      logger.info("   -> Expected RBAC tables/columns present; stamping database as 'head'...")
      run_command([sys.executable, "-m", "alembic", "stamp", "head"])

    else:
      logger.info("   -> Missing tables: %s", ", ".join(sorted(missing_tables)) if missing_tables else "(none)")
      logger.info("   -> Missing user columns: %s", ", ".join(sorted(missing_user_columns)) if missing_user_columns else "(none)")
      logger.info("   -> Skipping stamp; will apply migrations to add missing structures.")

  else:
    logger.info("✨ Fresh database detected. Proceeding with full migration.")

  logger.info("🚀 Applying migrations...")
  run_command([sys.executable, "-m", "alembic", "upgrade", "heads"])
  logger.info("✅ Migration complete.")


if __name__ == "__main__":
  if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    logger.info("Migration cancelled.")
    sys.exit(130)
  except Exception as e:
    logger.error("Unexpected error: %s", e)
    sys.exit(1)
