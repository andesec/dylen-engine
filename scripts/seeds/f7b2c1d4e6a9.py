"""Seed Gemini model pricing defaults."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_REQUIRED_COLUMNS: tuple[str, ...] = ("provider", "model", "input_per_1m", "output_per_1m", "is_active")


async def _table_exists(connection: AsyncConnection, *, table_name: str, schema: str | None = None) -> bool:
  """Return True when a table exists in the target schema."""
  # Default to public schema for seed safety checks.
  resolved_schema = schema or "public"
  # Query information_schema to avoid ORM reflection.
  statement = text(
    """
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = :schema
      AND table_name = :table_name
      AND table_type = 'BASE TABLE'
    LIMIT 1
    """
  )
  result = await connection.execute(statement, {"schema": resolved_schema, "table_name": table_name})
  return result.first() is not None


async def _column_exists(connection: AsyncConnection, *, table_name: str, column_name: str, schema: str | None = None) -> bool:
  """Return True when a column exists on the specified table."""
  # Default to public schema for seed safety checks.
  resolved_schema = schema or "public"
  # Query information_schema to avoid ORM reflection.
  statement = text(
    """
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = :schema
      AND table_name = :table_name
      AND column_name = :column_name
    LIMIT 1
    """
  )
  result = await connection.execute(statement, {"schema": resolved_schema, "table_name": table_name, "column_name": column_name})
  return result.first() is not None


async def _ensure_columns(connection: AsyncConnection, *, table_name: str, columns: tuple[str, ...]) -> bool:
  """Return True when all required columns exist on the table."""
  # Ensure the target table exists before inspecting columns.
  if not await _table_exists(connection, table_name=table_name):
    return False

  # Verify required columns so seeds do not crash on mismatched schemas.
  for column in columns:
    if not await _column_exists(connection, table_name=table_name, column_name=column):
      return False

  return True


async def _upsert_pricing(connection: AsyncConnection, *, provider: str, model: str, input_per_1m: float, output_per_1m: float) -> None:
  """Upsert pricing rows so seeds remain idempotent."""
  # Insert or update pricing rows to keep seed runs safe.
  await connection.execute(
    text(
      """
      INSERT INTO llm_model_pricing (provider, model, input_per_1m, output_per_1m, is_active)
      VALUES (:provider, :model, :input_per_1m, :output_per_1m, TRUE)
      ON CONFLICT (provider, model)
      DO UPDATE SET input_per_1m = EXCLUDED.input_per_1m,
                    output_per_1m = EXCLUDED.output_per_1m,
                    is_active = TRUE,
                    updated_at = now()
      """
    ),
    {"provider": provider, "model": model, "input_per_1m": float(input_per_1m), "output_per_1m": float(output_per_1m)},
  )


async def seed(connection: AsyncConnection) -> None:
  """Seed Gemini model pricing defaults."""
  # Ensure the pricing table is ready before inserting defaults.
  if not await _ensure_columns(connection, table_name="llm_model_pricing", columns=_REQUIRED_COLUMNS):
    return

  # Define baseline Gemini pricing in USD per 1M tokens.
  pricing_rows: list[dict[str, Any]] = [
    {"provider": "gemini", "model": "gemini-2.0-flash", "input_per_1m": 0.15, "output_per_1m": 0.6},
    {"provider": "gemini", "model": "gemini-2.0-flash-lite", "input_per_1m": 0.075, "output_per_1m": 0.3},
    {"provider": "gemini", "model": "gemini-2.5-flash", "input_per_1m": 0.3, "output_per_1m": 2.5},
    {"provider": "gemini", "model": "gemini-2.5-flash-image", "input_per_1m": 0.3, "output_per_1m": 30.0},
    {"provider": "gemini", "model": "gemini-2.5-pro", "input_per_1m": 1.25, "output_per_1m": 10.0},
  ]

  for row in pricing_rows:
    # Apply upserts for idempotent seed execution.
    await _upsert_pricing(connection, provider=str(row["provider"]), model=str(row["model"]), input_per_1m=float(row["input_per_1m"]), output_per_1m=float(row["output_per_1m"]))
