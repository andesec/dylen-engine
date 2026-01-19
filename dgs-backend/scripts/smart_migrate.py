import asyncio
import logging
import subprocess
import sys
from os.path import abspath, dirname

# Add project root to path
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from sqlalchemy import text
from app.core.database import get_db_engine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("smart_migrate")

async def check_db_state():
    engine = get_db_engine()
    try:
        async with engine.connect() as conn:
            # Check for alembic_version table
            result = await conn.execute(text("SELECT to_regclass('alembic_version')"))
            has_alembic = result.scalar() is not None

            # Check for users table
            result = await conn.execute(text("SELECT to_regclass('users')"))
            has_users = result.scalar() is not None

            # Check for profession column in users table
            has_profession = False
            if has_users:
                result = await conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name='users' AND column_name='profession'"
                ))
                has_profession = result.scalar() is not None
            
            return has_alembic, has_users, has_profession
    finally:
        await engine.dispose()

def run_command(cmd):
    logger.info(f"Running command: {cmd}")
    try:
        subprocess.run(cmd, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed with exit code {e.returncode}: {cmd}")
        sys.exit(e.returncode)

async def main():
    logger.info("Checking database state...")
    try:
        has_alembic, has_users, has_profession = await check_db_state()
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        sys.exit(1)

    if has_alembic:
        logger.info("✅ Database is already managed by Alembic.")
    elif has_users:
        logger.info("⚠️  Existing database detected WITHOUT Alembic history.")
        if has_profession:
            logger.info("   -> 'profession' column exists. Assumed up-to-date.")
            logger.info("   -> Stamping database as 'head'...")
            run_command("uv run alembic stamp head")
        else:
            logger.info("   -> 'profession' column MISSING.")
            logger.info("   -> Skipping stamp. Will attempt to apply migrations to add columns.")
    else:
        logger.info("✨ Fresh database detected. Proceeding with full migration.")

    logger.info("🚀 Applying migrations...")
    run_command("uv run alembic upgrade head")
    logger.info("✅ Migration complete.")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Migration cancelled.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
