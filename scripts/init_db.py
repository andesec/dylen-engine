"""Database initialization helper.

This script is intended for local/dev environments where a database may not exist yet.
It validates the target database name before using it in SQL, because CREATE DATABASE
cannot be parameterized in PostgreSQL.
"""

import asyncio
import os
import re
import sys

from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine

# Add the project root to the path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


_DB_NAME_PATTERN = re.compile(r"^[A-Za-z0-9]+$")


def _validate_database_name(db_name: str) -> str:
  """Validate a PostgreSQL database name used as an identifier.

  How/Why:
  - The name cannot be passed as a bind parameter for `CREATE DATABASE`.
  - Restricting to strict alphanumeric prevents SQL injection via identifier context.
  """
  # Ensure a non-empty string is provided before applying regex validation.
  if not db_name:
    raise ValueError("Target database name is empty.")

  # Only allow strict alphanumeric names so the value is safe in identifier context.
  if not _DB_NAME_PATTERN.fullmatch(db_name):
    raise ValueError("Target database name contains invalid characters (allowed: A-Z, a-z, 0-9).")

  return db_name


async def create_database_if_not_exists():
  """Create the configured database if it does not already exist."""
  # Import after path setup so the script works when run directly.
  from app.config import get_settings

  settings = get_settings()
  dsn = settings.pg_dsn

  if not dsn:
    print("Error: DYLEN_PG_DSN is not set.")
    sys.exit(1)

  url = make_url(dsn)
  target_db = _validate_database_name(url.database or "")

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
      result = await conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target_db})
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
