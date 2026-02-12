import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DSN = os.getenv("DYLEN_PG_DSN", "postgresql+asyncpg://dylen:dylen_password@localhost:5432/dylen")

if "asyncpg" not in DSN and "postgresql" in DSN:
  DSN = DSN.replace("postgresql://", "postgresql+asyncpg://")


async def reset_version():
  print(f"Connecting to {DSN.split('@')[-1]}...")
  engine = create_async_engine(DSN)

  try:
    async with engine.connect() as conn:
      print("Deleting all rows from alembic_version...")
      await conn.execute(text("DELETE FROM alembic_version"))
      await conn.commit()
      print("alembic_version cleared. Alembic will now see the DB as empty/unmigrated.")

  except Exception as e:
    print(f"Connection failed: {e}")
  finally:
    await engine.dispose()


if __name__ == "__main__":
  asyncio.run(reset_version())
