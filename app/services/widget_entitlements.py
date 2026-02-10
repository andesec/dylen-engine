from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

_TIER_RANK: dict[str, int] = {"none": 0, "flash": 1, "reasoning": 2}
_WIDGET_MIN_TIER: dict[str, str] = {
  # Fenster widgets are subscription-gated and require at least flash tier access.
  "fenster": "flash"
}


def _normalize_tier(value: Any) -> str:
  """Normalize runtime tier strings to known entitlement values."""
  # Default to deny-by-default posture when runtime config is missing or invalid.
  normalized = str(value or "").strip().lower()
  if normalized not in _TIER_RANK:
    return "none"
  return normalized


def validate_widget_entitlements(widgets: list[str] | None, *, runtime_config: dict[str, Any]) -> None:
  """Validate that requested widgets are allowed for the effective subscription tier."""
  # Skip entitlement checks when clients rely on server-selected defaults.
  if not widgets:
    return

  selected = [str(widget).strip() for widget in widgets if str(widget).strip()]
  if not selected:
    return

  current_tier = _normalize_tier(runtime_config.get("fenster.widgets_tier"))
  blocked: list[str] = []
  min_required: str | None = None

  for widget in selected:
    required_tier = _WIDGET_MIN_TIER.get(widget)
    if not required_tier:
      continue
    if _TIER_RANK[current_tier] < _TIER_RANK[required_tier]:
      blocked.append(widget)
      if min_required is None or _TIER_RANK[required_tier] > _TIER_RANK[min_required]:
        min_required = required_tier

  if blocked:
    unique_blocked = sorted(set(blocked))
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"error": "UPGRADE_REQUIRED", "feature": "widget", "widgets": unique_blocked, "min_tier": min_required or "flash"})
