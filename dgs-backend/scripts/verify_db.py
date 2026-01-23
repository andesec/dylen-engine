import asyncio
import sys
from os.path import abspath, dirname

# Ensure app is in path
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from sqlalchemy import inspect  # noqa: E402

from app.core.database import get_db_engine  # noqa: E402


async def main():
  engine = get_db_engine()
  try:
    async with engine.connect() as conn:

      def _inspect(sync_conn):
        inspector = inspect(sync_conn)
        tables = set(inspector.get_table_names())
        if "users" not in tables:
          return False, False
        columns = {col.get("name") for col in inspector.get_columns("users")}
        has_profession = "profession" in columns
        has_lessons = "dgs_lessons" in tables
        return has_profession, has_lessons

      has_profession, has_lessons = await conn.run_sync(_inspect)
      if has_profession:
        print("SUCCESS: profession column exists!")
      else:
        print("FAILURE: profession column missing!")
        sys.exit(1)

      if has_lessons:
        print("SUCCESS: dgs_lessons table exists!")
      else:
        print("FAILURE: dgs_lessons table missing!")
        sys.exit(1)
  finally:
    await engine.dispose()


if __name__ == "__main__":
  asyncio.run(main())
