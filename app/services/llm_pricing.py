"""Load LLM pricing configuration from the database."""

from __future__ import annotations

from typing import Any

from app.schema.llm_pricing import LlmModelPricing
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

PricingTable = dict[str, dict[str, tuple[float, float]]]


def _normalize_provider(value: Any) -> str:
  """Normalize provider identifiers for pricing lookups."""
  normalized = str(value or "").strip().lower()
  return normalized


def _normalize_model(value: Any) -> str:
  """Normalize model identifiers for pricing lookups."""
  normalized = str(value or "").strip()
  return normalized


async def load_pricing_table(session: AsyncSession) -> PricingTable:
  """Load active model pricing into a provider->model mapping."""
  # Start with an empty map so callers can handle missing data safely.
  pricing_table: PricingTable = {}
  # Only load active rows to avoid stale or disabled pricing entries.
  stmt = select(LlmModelPricing.provider, LlmModelPricing.model, LlmModelPricing.input_per_1m, LlmModelPricing.output_per_1m).where(LlmModelPricing.is_active.is_(True))
  result = await session.execute(stmt)
  rows = result.all()
  for provider, model, input_rate, output_rate in rows:
    # Normalize keys so lookups are stable across casing or whitespace.
    normalized_provider = _normalize_provider(provider)
    normalized_model = _normalize_model(model)
    if normalized_provider == "" or normalized_model == "":
      continue

    # Insert the normalized pricing row into the provider map.
    provider_rates = pricing_table.setdefault(normalized_provider, {})
    provider_rates[normalized_model] = (float(input_rate or 0.0), float(output_rate or 0.0))

  return pricing_table
