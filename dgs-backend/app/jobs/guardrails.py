"""Guardrails to keep DynamoDB job items within safe size limits."""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from decimal import Decimal
from typing import Any

MAX_ITEM_BYTES = 380_000
MAX_LOG_ENTRY_BYTES = 2_000
MAX_LOG_ENTRIES = 200
MAX_RESULT_BYTES = 200_000
MAX_ARTIFACT_BYTES = 200_000


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def estimate_bytes(value: Any) -> int:
    """Approximate the DynamoDB item size using JSON encoding."""
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), cls=DecimalEncoder)
    return len(payload.encode("utf-8"))


def sanitize_logs(logs: list[str]) -> list[str]:
    """Clamp log entry lengths and total log volume."""
    trimmed_entries = [entry[:MAX_LOG_ENTRY_BYTES] for entry in logs]
    if len(trimmed_entries) > MAX_LOG_ENTRIES:
        trimmed_entries = trimmed_entries[-MAX_LOG_ENTRIES:]
    return trimmed_entries


def maybe_truncate_result_json(result_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep result payloads under the configured size budget."""
    if result_json is None:
        return None
    if estimate_bytes(result_json) <= MAX_RESULT_BYTES:
        return result_json
    preview = json.dumps(result_json, ensure_ascii=True, cls=DecimalEncoder)
    return {
        "truncated": True,
        "preview": preview[:MAX_RESULT_BYTES],
        "message": "Result exceeded DynamoDB item size limit and was truncated.",
    }


def maybe_truncate_artifacts(artifacts: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep artifacts payloads under the configured size budget."""
    if artifacts is None:
        return None
    if estimate_bytes(artifacts) <= MAX_ARTIFACT_BYTES:
        return artifacts
    preview = json.dumps(artifacts, ensure_ascii=True, cls=DecimalEncoder)
    return {
        "truncated": True,
        "preview": preview[:MAX_ARTIFACT_BYTES],
        "message": "Artifacts exceeded DynamoDB item size limit and were truncated.",
    }


def enforce_item_size_guardrails(
    item: MutableMapping[str, Any],
    *,
    max_bytes: int = MAX_ITEM_BYTES,
    skip_size_check: bool = False,
) -> MutableMapping[str, Any]:
    """
    Ensure a DynamoDB item fits within size constraints by trimming logs when necessary.

    If the item still exceeds the threshold after trimming, a sentinel log message is used.
    """
    if "logs" in item and isinstance(item["logs"], list):
        item["logs"] = sanitize_logs(item["logs"])

    if skip_size_check:
        return item

    size = estimate_bytes(item)
    if size <= max_bytes:
        return item

    # Try keeping the most recent 50 logs
    logs = item.get("logs")
    if isinstance(logs, list):
        item["logs"] = logs[-50:]
        item["logs"] = sanitize_logs(item["logs"])
        size = estimate_bytes(item)

    if size > max_bytes:
        item["logs"] = ["<logs truncated to satisfy DynamoDB item size>"]

    return item
