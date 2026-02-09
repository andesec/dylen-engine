import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.append(os.getcwd())

from app.config import get_database_settings


async def main():
  settings = get_database_settings()
  database_url = settings.pg_dsn.replace("postgresql://", "postgresql+asyncpg://")
  engine = create_async_engine(database_url)

  async with engine.connect() as conn:
    result = await conn.execute(text("SELECT * FROM alembic_version"))
    rows = result.fetchall()
    print(f"alembic_version: {rows}")

    try:
      await conn.execute(text("SELECT 1 FROM illustration_assets LIMIT 1"))
      print("illustration_assets table exists")
    except Exception as e:
      print(f"illustration_assets table does not exist: {e}")

  await engine.dispose()


if __name__ == "__main__":
  asyncio.run(main())
