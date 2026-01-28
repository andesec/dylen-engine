from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _normalize_async_dsn(dsn: str) -> str:
  """Normalize sync Postgres URLs so scripts consistently use asyncpg."""
  if dsn.startswith("postgresql://"):
    return dsn.replace("postgresql://", "postgresql+asyncpg://", 1)

  return dsn


async def _check_subscription_tiers(*, dsn: str) -> list[str]:
  """Validate required subscription tiers exist so quota logic never 500s."""
  required = ["Free", "Plus", "Pro"]
  engine = create_async_engine(dsn)
  try:
    async with engine.connect() as connection:
      # Read-only query to validate reference data presence deterministically.
      result = await connection.execute(text("select name from subscription_tiers where name = any(:names)"), {"names": required})
      found = {row[0] for row in result.fetchall()}
      missing = [name for name in required if name not in found]
      return missing

  finally:
    await engine.dispose()


def main() -> None:
  """Exit non-zero when required static seed data is missing."""
  # Support both env var names so the check works during repo renames.
  dsn = (os.getenv("DYLEN_PG_DSN", "") or os.getenv("DGS_PG_DSN", "")).strip()
  if not dsn:
    print("ERROR: DYLEN_PG_DSN (or DGS_PG_DSN) is required for seed-data checks.")
    sys.exit(1)

  normalized_dsn = _normalize_async_dsn(dsn)
  try:
    missing = asyncio.run(_check_subscription_tiers(dsn=normalized_dsn))
  except Exception as exc:
    print(f"ERROR: Seed-data check failed: {exc}")
    sys.exit(1)

  if missing:
    print("ERROR: Required subscription_tiers rows are missing:")
    for name in missing:
      print(f"- {name}")
    print("Remediation: run migrations (alembic upgrade head) to apply seed migrations.")
    sys.exit(1)

  print("OK: Seed-data check passed.")


if __name__ == "__main__":
  main()
