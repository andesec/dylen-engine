"""Verify strict feature-flag matrix completeness for tiers and organizations."""

from __future__ import annotations

import asyncio
import os

from app.utils.env import default_env_path, load_env_file
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def _normalize_async_dsn(raw_dsn: str) -> str:
  """Normalize postgres DSN into asyncpg format for async SQLAlchemy usage."""
  candidate = raw_dsn.strip()
  if candidate.startswith("postgresql+asyncpg://"):
    return candidate
  if candidate.startswith("postgresql://"):
    return candidate.replace("postgresql://", "postgresql+asyncpg://", 1)
  if candidate.startswith("postgres://"):
    return candidate.replace("postgres://", "postgresql+asyncpg://", 1)
  return candidate


async def _run() -> None:
  """Run matrix completeness checks and print actionable results."""
  # Load environment once so local development matches service startup behavior.
  load_env_file(default_env_path(), override=False)
  raw_dsn = (os.getenv("DYLEN_PG_DSN") or "").strip()
  if raw_dsn == "":
    raise RuntimeError("DYLEN_PG_DSN must be set.")
  engine = create_async_engine(_normalize_async_dsn(raw_dsn))
  try:
    async with engine.connect() as connection:
      # Detect missing permission feature-flag definitions.
      missing_perm_flags_result = await connection.execute(
        text(
          """
          SELECT p.slug
          FROM permissions p
          LEFT JOIN feature_flags ff ON ff.key = ('perm.' || p.slug)
          WHERE ff.id IS NULL
          ORDER BY p.slug
          """
        )
      )
      missing_perm_flags = [str(row[0]) for row in missing_perm_flags_result.fetchall()]
      # Detect missing strict tier matrix rows.
      missing_tier_rows_result = await connection.execute(
        text(
          """
          SELECT st.name, ff.key
          FROM subscription_tiers st
          CROSS JOIN feature_flags ff
          LEFT JOIN subscription_tier_feature_flags stff
            ON stff.subscription_tier_id = st.id
           AND stff.feature_flag_id = ff.id
          WHERE stff.feature_flag_id IS NULL
          ORDER BY st.name, ff.key
          """
        )
      )
      missing_tier_rows = missing_tier_rows_result.fetchall()
      # Detect missing strict tenant matrix rows.
      missing_org_rows_result = await connection.execute(
        text(
          """
          SELECT o.id, ff.key
          FROM organizations o
          CROSS JOIN feature_flags ff
          LEFT JOIN organization_feature_flags off
            ON off.org_id = o.id
           AND off.feature_flag_id = ff.id
          WHERE off.feature_flag_id IS NULL
          ORDER BY o.id, ff.key
          """
        )
      )
      missing_org_rows = missing_org_rows_result.fetchall()
      print(f"missing_perm_flags={len(missing_perm_flags)}")
      if missing_perm_flags:
        for slug in missing_perm_flags[:50]:
          print(f"  perm_flag_missing: {slug}")
      print(f"missing_tier_rows={len(missing_tier_rows)}")
      if missing_tier_rows:
        for tier_name, flag_key in missing_tier_rows[:50]:
          print(f"  tier_row_missing: tier={tier_name} flag={flag_key}")
      print(f"missing_org_rows={len(missing_org_rows)}")
      if missing_org_rows:
        for org_id, flag_key in missing_org_rows[:50]:
          print(f"  org_row_missing: org_id={org_id} flag={flag_key}")
      if missing_perm_flags or missing_tier_rows or missing_org_rows:
        raise RuntimeError("Feature flag matrix verification failed.")
      print("feature_flag_matrix=ok")
  finally:
    await engine.dispose()


if __name__ == "__main__":
  asyncio.run(_run())
