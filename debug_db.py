import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.append(os.getcwd())

from app.config import get_database_settings


async def main():
  settings = get_database_settings()
  print(f"Connecting to {settings.pg_dsn}")
  database_url = settings.pg_dsn.replace("postgresql://", "postgresql+asyncpg://")
  engine = create_async_engine(database_url, echo=True)

  async with engine.begin() as conn:
    print("Creating test table...")
    await conn.execute(text("CREATE TABLE IF NOT EXISTS debug_test (id serial PRIMARY KEY, val text)"))
    print("Inserting value...")
    await conn.execute(text("INSERT INTO debug_test (val) VALUES ('hello')"))

  print("Transaction committed (hopefully). checking...")

  async with engine.connect() as conn:
    result = await conn.execute(text("SELECT * FROM debug_test"))
    rows = result.fetchall()
    print(f"Rows: {rows}")

    await conn.execute(text("DROP TABLE debug_test"))
    await conn.commit()

  await engine.dispose()


if __name__ == "__main__":
  asyncio.run(main())
