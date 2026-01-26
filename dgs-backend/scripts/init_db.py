import asyncio
import os
import sys

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from sqlalchemy.engine.url import make_url

# Add the project root to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings


async def create_database_if_not_exists():
  settings = get_settings()
  dsn = settings.pg_dsn

  if not dsn:
    print("Error: DGS_PG_DSN is not set.")
    sys.exit(1)

  url = make_url(dsn)
  target_db = url.database

  # Connect to the default 'postgres' database to check/create the target DB
  # We need to modify the URL to point to 'postgres' database
  postgres_url = url.set(database="postgres")

  # Ensure we are using the async driver
  if postgres_url.drivername.startswith("postgresql") and "+asyncpg" not in postgres_url.drivername:
    postgres_url = postgres_url.set(drivername="postgresql+asyncpg")

  print(f"Connecting to postgres to check for database '{target_db}'...")

  # We need isolation_level="AUTOCOMMIT" to CREATE DATABASE
  engine = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")

  try:
    async with engine.connect() as conn:
      # Check if database exists
      result = await conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{target_db}'"))
      exists = result.scalar() == 1

      if not exists:
        print(f"Database '{target_db}' does not exist. Creating...")
        await conn.execute(text(f'CREATE DATABASE "{target_db}"'))
        print(f"Database '{target_db}' created successfully.")
      else:
        print(f"Database '{target_db}' already exists.")

  except Exception as e:
    print(f"Error checking/creating database: {e}")
    sys.exit(1)
  finally:
    await engine.dispose()


if __name__ == "__main__":
  if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
  asyncio.run(create_database_if_not_exists())
