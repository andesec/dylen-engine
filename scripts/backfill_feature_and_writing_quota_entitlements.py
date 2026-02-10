"""Backfill tier feature flags and writing-check quotas for existing environments."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Ensure repo root is on sys.path so local imports resolve before site-packages.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.env import default_env_path, load_env_file

_PRODUCT_FEATURES: tuple[tuple[str, str], ...] = (("feature.research", "Enable research workflows."), ("feature.writing", "Enable writing checks."), ("feature.ocr", "Enable OCR extraction."), ("feature.fenster", "Enable fenster widgets."))
_FEATURE_TIER_ENABLEMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (("feature.research", ("Starter", "Plus", "Pro")), ("feature.writing", ("Starter", "Plus", "Pro")), ("feature.ocr", ("Starter", "Plus", "Pro")), ("feature.fenster", ("Plus", "Pro")))
_WRITING_CHECK_LIMITS_PER_TIER: tuple[tuple[str, int], ...] = (("Free", 0), ("Starter", 30), ("Plus", 120), ("Pro", 500))


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
  """Execute idempotent entitlement backfills for tier feature flags and quotas."""
  # Load env so local execution mirrors service startup configuration.
  load_env_file(default_env_path(), override=False)
  raw_dsn = (os.getenv("DYLEN_PG_DSN") or "").strip()
  if raw_dsn == "":
    raise RuntimeError("DYLEN_PG_DSN must be set.")
  engine = create_async_engine(_normalize_async_dsn(raw_dsn))
  try:
    async with engine.begin() as connection:
      # Keep product feature flag definitions available before tier assignments.
      for key, description in _PRODUCT_FEATURES:
        await connection.execute(
          text(
            """
            INSERT INTO feature_flags (id, key, description, default_enabled)
            VALUES (:id, :key, :description, :default_enabled)
            ON CONFLICT (key) DO UPDATE
            SET description = EXCLUDED.description
            """
          ),
          {"id": uuid.uuid4(), "key": key, "description": description, "default_enabled": False},
        )

      # Resolve tier and feature identifiers in one pass for deterministic upserts.
      tier_rows = await connection.execute(text("SELECT id, name FROM subscription_tiers"))
      tier_ids = {str(row[1]): int(row[0]) for row in tier_rows.fetchall()}
      feature_rows = await connection.execute(text("SELECT id, key FROM feature_flags"))
      feature_ids = {str(row[1]): row[0] for row in feature_rows.fetchall()}

      # Grant tier-level feature access through explicit matrix rows.
      for feature_key, tier_names in _FEATURE_TIER_ENABLEMENTS:
        feature_flag_id = feature_ids.get(feature_key)
        if feature_flag_id is None:
          continue
        for tier_name in tier_names:
          tier_id = tier_ids.get(tier_name)
          if tier_id is None:
            continue
          await connection.execute(
            text(
              """
              INSERT INTO subscription_tier_feature_flags (subscription_tier_id, feature_flag_id, enabled)
              VALUES (:subscription_tier_id, :feature_flag_id, :enabled)
              ON CONFLICT (subscription_tier_id, feature_flag_id) DO UPDATE
              SET enabled = EXCLUDED.enabled
              """
            ),
            {"subscription_tier_id": tier_id, "feature_flag_id": feature_flag_id, "enabled": True},
          )

      # Add writing quota limits at tier scope so writing-enabled tiers are usable.
      for tier_name, writing_limit in _WRITING_CHECK_LIMITS_PER_TIER:
        tier_id = tier_ids.get(tier_name)
        if tier_id is None:
          continue
        await connection.execute(
          text(
            """
            INSERT INTO runtime_config_values (id, key, scope, subscription_tier_id, value_json)
            VALUES (:id, :key, :scope, :subscription_tier_id, CAST(:value_json AS jsonb))
            ON CONFLICT (key, subscription_tier_id) WHERE scope = 'TIER' DO UPDATE
            SET value_json = EXCLUDED.value_json
            """
          ),
          {"id": uuid.uuid4(), "key": "limits.writing_checks_per_month", "scope": "TIER", "subscription_tier_id": tier_id, "value_json": json.dumps(writing_limit)},
        )
      # Print resulting rows so operators can confirm effective backfills quickly.
      writing_flag_rows = await connection.execute(
        text(
          """
          SELECT st.name, stff.enabled
          FROM subscription_tier_feature_flags stff
          JOIN subscription_tiers st ON st.id = stff.subscription_tier_id
          JOIN feature_flags ff ON ff.id = stff.feature_flag_id
          WHERE ff.key = 'feature.writing'
          ORDER BY st.id
          """
        )
      )
      print(f"feature.writing={writing_flag_rows.fetchall()}")
      writing_limit_rows = await connection.execute(
        text(
          """
          SELECT st.name, rcv.value_json
          FROM runtime_config_values rcv
          JOIN subscription_tiers st ON st.id = rcv.subscription_tier_id
          WHERE rcv.scope = 'TIER'
            AND rcv.key = 'limits.writing_checks_per_month'
          ORDER BY st.id
          """
        )
      )
      print(f"limits.writing_checks_per_month={writing_limit_rows.fetchall()}")
  finally:
    await engine.dispose()


if __name__ == "__main__":
  asyncio.run(_run())
