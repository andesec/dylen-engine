"""Audit logging for LLM requests to Postgres."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.telemetry.context import get_llm_call_context

if TYPE_CHECKING:
  from app.storage.postgres_audit_repo import LlmAuditRecord, PostgresLlmAuditRepository


@dataclass(frozen=True)
class LlmAuditStart:
  """Carry the request details needed to insert a pending LLM call row."""

  provider: str
  model: str
  request_type: str
  request_payload: str
  started_at: datetime


def _audit_enabled() -> bool:
  """Return True when LLM audit logging is explicitly enabled."""
  settings = get_settings()

  return bool(settings.llm_audit_enabled and settings.pg_dsn)


@lru_cache(maxsize=1)
def _get_repository() -> PostgresLlmAuditRepository | None:
  """Cache the repository so repeated inserts reuse configuration."""
  settings = get_settings()

  # Refuse to create a repository when audit logging is disabled or misconfigured.

  if not settings.llm_audit_enabled or not settings.pg_dsn:
    return None

  # Import lazily so psycopg is only required when audit logging is active.

  try:
    from app.storage.postgres_audit_repo import PostgresLlmAuditRepository

  except ImportError as exc:
    logger = logging.getLogger(__name__)

    logger.warning("LLM audit disabled because psycopg is unavailable: %s", exc)

    return None

  return PostgresLlmAuditRepository()


async def start_llm_call(*, provider: str, model: str, request_type: str, request_payload: str, started_at: datetime) -> int | None:
  """Insert a pending LLM call row before the network request."""
  # Exit early when audit logging is disabled to keep calls fast.

  if not _audit_enabled():
    return None

  repo = _get_repository()

  # Skip persistence when the repository cannot be initialized.

  if repo is None:
    return None

  # Scrub PII from payload before storage.
  safe_payload = _scrub_pii(request_payload)

  # Build the record and insert asynchronously.
  event = LlmAuditStart(provider=provider, model=model, request_type=request_type, request_payload=safe_payload or "", started_at=started_at)
  record = _build_pending_record(event)

  return await _insert_record(repo, record)


async def finalize_llm_call(*, call_id: int | None, response_payload: str | None, usage: dict[str, int] | None, duration_ms: int, error: BaseException | None) -> None:
  """Update the pending LLM call row after the response or failure."""
  # Avoid update attempts when the insert did not happen.

  if call_id is None:
    return

  # Exit early when audit logging is disabled to keep calls fast.

  if not _audit_enabled():
    return

  repo = _get_repository()

  # Skip persistence when the repository cannot be initialized.

  if repo is None:
    return

  finished_at = utc_now()
  status = "error" if error else "success"
  error_message = str(error) if error else None
  prompt_tokens = None
  completion_tokens = None
  total_tokens = None

  # Pull token usage into normalized integer fields when data is provided.

  if usage:
    prompt_tokens = _coerce_int(usage.get("prompt_tokens"))
    completion_tokens = _coerce_int(usage.get("completion_tokens"))
    total_tokens = _coerce_int(usage.get("total_tokens"))

  # Scrub PII from response before storage.
  safe_response = _scrub_pii(response_payload)

  await _update_record(
    repo, call_id, finished_at=finished_at, response_payload=safe_response, status=status, error_message=error_message, duration_ms=duration_ms, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total_tokens
  )


def _build_pending_record(event: LlmAuditStart) -> LlmAuditRecord:
  """Build a pending LLM audit record using the active call context."""
  # Import lazily to avoid requiring psycopg when audit logging is disabled.
  from app.storage.postgres_audit_repo import LlmAuditRecord

  # Capture call context so audit rows can be traced to a job and agent.
  context = get_llm_call_context()
  agent = context.agent if context else "unknown"
  lesson_topic = context.lesson_topic if context else None
  job_id = context.job_id if context else None
  purpose = context.purpose if context else None
  call_index = context.call_index if context else None

  return LlmAuditRecord(
    record_id=0,
    timestamp_request=event.started_at,
    timestamp_response=None,
    started_at=event.started_at,
    duration_ms=0,
    agent=agent,
    provider=event.provider,
    model=event.model,
    lesson_topic=lesson_topic,
    request_payload=event.request_payload,
    response_payload=None,
    prompt_tokens=None,
    completion_tokens=None,
    total_tokens=None,
    request_type=event.request_type,
    purpose=purpose,
    call_index=call_index,
    job_id=job_id,
    status="pending",
    error_message=None,
  )


async def _insert_record(repo: PostgresLlmAuditRepository, record: LlmAuditRecord) -> int | None:
  """Insert a record and swallow database failures to avoid breaking calls."""
  logger = logging.getLogger(__name__)

  try:
    return await repo.insert_record(record)

  except Exception as exc:  # noqa: BLE001 - avoid breaking upstream calls
    logger.warning("Failed to insert LLM audit record: %s", exc)
    return None


async def _update_record(
  repo: PostgresLlmAuditRepository, record_id: int, *, finished_at: datetime, response_payload: str | None, status: str, error_message: str | None, duration_ms: int, prompt_tokens: int | None, completion_tokens: int | None, total_tokens: int | None
) -> None:
  """Update an existing audit record and swallow database failures."""
  logger = logging.getLogger(__name__)

  try:
    await repo.update_record(
      record_id=record_id, timestamp_response=finished_at, response_payload=response_payload, status=status, error_message=error_message, duration_ms=duration_ms, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=total_tokens
    )

  except Exception as exc:  # noqa: BLE001 - avoid breaking upstream calls
    logger.warning("Failed to update LLM audit record: %s", exc)


def _coerce_int(value: Any) -> int | None:
  """Normalize token values to integers when present."""

  # Treat missing values as absent tokens.

  if value is None:
    return None

  # Preserve boolean semantics for providers that mis-type token counts.

  if isinstance(value, bool):
    return int(value)

  # Coerce numeric values to integers for storage normalization.

  if isinstance(value, (int, float)):
    return int(value)

  return None


def serialize_request(prompt: str, schema: dict[str, Any] | None) -> str:
  """Serialize request content so it can be stored as text."""
  # Preserve the prompt when there is no schema context.

  if schema is None:
    return prompt

  # Encode prompt+schema as JSON for structured requests.

  return json.dumps({"prompt": prompt, "schema": schema}, ensure_ascii=True)


def serialize_response(value: Any) -> str | None:
  """Serialize response content so it can be stored as text."""

  # Represent missing responses as null in storage.

  if value is None:
    return None

  # Preserve strings as-is to avoid unnecessary encoding.

  if isinstance(value, str):
    return value

  # Fall back to string conversion when JSON encoding fails.

  try:
    return json.dumps(value, ensure_ascii=True)

  except (TypeError, ValueError):
    return str(value)


def utc_now() -> datetime:
  """Return a UTC timestamp for audit records."""
  return datetime.now(tz=UTC)


def _scrub_pii(text: str | None) -> str | None:
  """Redact common PII patterns from audit logs."""
  if not text:
    return text

  # Redact Email
  text = re.sub(r"[\w\.-]+@[\w\.-]+\.\w+", "[EMAIL REDACTED]", text)

  # Redact Phone (simple pattern: 3-3-4 digits with separators)
  text = re.sub(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE REDACTED]", text)

  return text
