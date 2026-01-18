"""Cost tracking scaffolding for AI usage."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UsageEntry:
    """Usage metadata for a single model call."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CostTracker:
    """Accumulates usage and cost estimates for a generation job."""

    pricing_table: dict[str, tuple[float, float]] = field(default_factory=dict)
    usage: list[UsageEntry] = field(default_factory=list)

    def record(self, entry: UsageEntry) -> float:
        """Record usage and return the estimated cost for this entry."""
        self.usage.append(entry)
        return self._estimate_entry_cost(entry)

    def total_cost(self) -> float:
        """Return the total estimated cost for all recorded entries."""
        total = 0.0
        for entry in self.usage:
            total += self._estimate_entry_cost(entry)
        return round(total, 6)

    def _estimate_entry_cost(self, entry: UsageEntry) -> float:
        price_in, price_out = self.pricing_table.get(entry.model, (0.0, 0.0))
        call_cost = (entry.prompt_tokens / 1_000_000) * price_in
        call_cost += (entry.completion_tokens / 1_000_000) * price_out
        return round(call_cost, 6)
