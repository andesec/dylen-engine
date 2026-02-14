from __future__ import annotations

from typing import Any

PricingTable = dict[str, dict[str, tuple[float, float]]]


def calculate_total_cost(usage: list[dict[str, Any]], pricing_table: PricingTable | None = None, provider: str | None = None) -> float:
  """Estimate total cost based on token usage."""
  # Default to a zeroed pricing table if none is provided.
  pricing = pricing_table or {}
  # Normalize the provider to keep pricing lookups stable.
  fallback_provider = str(provider or "gemini").strip().lower()

  total = 0.0
  for entry in usage:
    # Normalize pricing lookup keys per usage entry.
    entry_provider = str(entry.get("provider") or fallback_provider).strip().lower()
    model = str(entry.get("model") or "").strip()
    provider_rates = pricing.get(entry_provider, {})
    price_in, price_out = provider_rates.get(model, (0.0, 0.0))

    # Normalize token counts for consistent cost output.
    in_tokens = int(entry.get("prompt_tokens") or 0)
    out_tokens = int(entry.get("completion_tokens") or 0)

    call_cost = (in_tokens / 1_000_000) * price_in
    call_cost += (out_tokens / 1_000_000) * price_out

    entry["input_tokens"] = in_tokens
    entry["output_tokens"] = out_tokens
    entry["estimated_cost"] = round(call_cost, 6)

    total += call_cost

  return round(total, 6)
