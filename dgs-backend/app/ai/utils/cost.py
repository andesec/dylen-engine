from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _load_pricing_table() -> dict[str, tuple[float, float]]:
  default_prices = {
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.075, 0.30),
    "gemini-2.0-flash-exp": (0.0, 0.0),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 5.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (5.0, 15.0),
    "anthropic/claude-3.5-sonnet": (3.0, 15.0),
  }
  raw = os.getenv("MODEL_PRICING_JSON")
  if not raw:
    return default_prices
  try:
    parsed = json.loads(raw)
  except json.JSONDecodeError:
    return default_prices

  if not isinstance(parsed, dict):
    return default_prices

  prices = dict(default_prices)
  for model, value in parsed.items():
    if not isinstance(value, dict):
      continue
    price_in = value.get("input")
    price_out = value.get("output")
    if isinstance(price_in, (int, float)) and isinstance(price_out, (int, float)):
      prices[str(model)] = (float(price_in), float(price_out))
  return prices


def calculate_total_cost(usage: list[dict[str, Any]]) -> float:
  """Estimate total cost based on token usage."""
  # Price table can be overridden via MODEL_PRICING_JSON.
  pricing = _load_pricing_table()

  total = 0.0
  for entry in usage:
    model = entry.get("model", "")
    price_in, price_out = pricing.get(model, (0.5, 1.5))

    in_tokens = int(entry.get("prompt_tokens") or 0)
    out_tokens = int(entry.get("completion_tokens") or 0)

    call_cost = (in_tokens / 1_000_000) * price_in
    call_cost += (out_tokens / 1_000_000) * price_out

    entry["input_tokens"] = in_tokens
    entry["output_tokens"] = out_tokens
    entry["estimated_cost"] = round(call_cost, 6)

    total += call_cost

  return round(total, 6)
