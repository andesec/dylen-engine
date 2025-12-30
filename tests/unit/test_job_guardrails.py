from app.jobs.guardrails import (
    MAX_LOG_ENTRIES,
    MAX_LOG_ENTRY_BYTES,
    enforce_item_size_guardrails,
    estimate_bytes,
    maybe_truncate_result_json,
    sanitize_logs,
)


def test_sanitize_logs_limits_length_and_count() -> None:
    long_entry = "a" * (MAX_LOG_ENTRY_BYTES + 10)
    logs = [long_entry] * (MAX_LOG_ENTRIES + 5)
    sanitized = sanitize_logs(logs)
    assert len(sanitized) == MAX_LOG_ENTRIES
    assert all(len(entry) <= MAX_LOG_ENTRY_BYTES for entry in sanitized)


def test_enforce_item_size_guardrails_truncates_logs() -> None:
    item = {"logs": ["a" * 10_000] * (MAX_LOG_ENTRIES + 10), "request": {"topic": "t"}}
    trimmed = enforce_item_size_guardrails(item, max_bytes=1_000)
    assert trimmed["logs"]
    assert estimate_bytes(trimmed) <= 1_000


def test_maybe_truncate_result_json_returns_preview_when_large() -> None:
    large_payload = {"data": "x" * 300_000}
    truncated = maybe_truncate_result_json(large_payload)
    assert truncated is not None
    assert truncated.get("truncated") is True
    assert "preview" in truncated
