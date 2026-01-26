import os
import subprocess
import sys
from sqlalchemy import create_engine, inspect, text

# Add the project root to the path so we can import 'app' if needed, though we primarily shell out.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings


def run_alembic_command(command_args):
  """Run an alembic command via subprocess."""
  cmd = ["alembic"] + command_args
  print(f"Running: {' '.join(cmd)}")
  result = subprocess.run(cmd, check=False)
  if result.returncode != 0:
    print(f"Error running alembic command: {' '.join(cmd)}")
    sys.exit(result.returncode)


def main():
  settings = get_settings()

  # We use the synchronous driver for inspection/setup logic here
  # The DSN in settings is typically async (postgresql+asyncpg://)
  # We need a sync DSN for sqlalchemy engine (postgresql:// or postgresql+psycopg2://)
  dsn = settings.pg_dsn
  if "asyncpg" in dsn:
    dsn = dsn.replace("+asyncpg", "")

  print(f"Connecting to database to check state...")
  try:
    # We simply want to ensure the database is up to date.
    # The migrations themselves (e.g. baseline) should handle "if not exists" checks
    # for table creation to be safe against existing legacy tables.
    print("Running full migration (upgrade head)...")
    run_alembic_command(["upgrade", "head"])

  except Exception as e:
    print(f"Critical error during migration check: {e}")
    sys.exit(1)


if __name__ == "__main__":
  main()
