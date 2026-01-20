import asyncio
import sys
from os.path import abspath, dirname

# Ensure app is in path
sys.path.insert(0, dirname(dirname(abspath(__file__))))

from sqlalchemy import text
from app.core.database import get_db_engine


async def main():
  engine = get_db_engine()
  try:
    async with engine.connect() as conn:
      # Check users column
      result = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='profession'"))
      val = result.scalar()
      if val == "profession":
        print("SUCCESS: profession column exists!")
      else:
        print("FAILURE: profession column missing!")
        sys.exit(1)

      # Check dgs_lessons table
      result = await conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_name='dgs_lessons'"))
      val = result.scalar()
      if val == "dgs_lessons":
        print("SUCCESS: dgs_lessons table exists!")
      else:
        print("FAILURE: dgs_lessons table missing!")
        sys.exit(1)
  finally:
    await engine.dispose()


if __name__ == "__main__":
  asyncio.run(main())
