"""Database transaction retry logic with retryable vs non-retryable error classification."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

logger = logging.getLogger(__name__)


class DBFailureClassification:
  """Classification result for a database failure."""

  def __init__(self, *, retryable: bool, reason: str, sqlstate: str | None, category: str) -> None:
    self.retryable = retryable
    self.reason = reason
    self.sqlstate = sqlstate
    self.category = category


def _extract_sqlstate(exc: Exception) -> str | None:
  """Extract Postgres SQLSTATE from SQLAlchemy exception."""
  if isinstance(exc, DBAPIError) and hasattr(exc, "orig"):
    # Try pgcode first (psycopg2/psycopg3)
    if hasattr(exc.orig, "pgcode") and exc.orig.pgcode:
      return str(exc.orig.pgcode)
    # Try sqlstate (some drivers)
    if hasattr(exc.orig, "sqlstate") and exc.orig.sqlstate:
      return str(exc.orig.sqlstate)
  return None


def classify_db_failure(exc: Exception) -> DBFailureClassification:
  """
  Classify database failure as retryable or non-retryable.

  Primary signal: Postgres SQLSTATE
  Fallback: Exception type and message patterns

  Retryable errors (transient):
    - 40001: serialization failure
    - 40P01: deadlock detected
    - 55P03: lock not available (NOWAIT)
    - 57014: query canceled (timeout)
    - Connection drops/resets

  Non-retryable errors (permanent):
    - 23xxx: integrity violations (unique, FK, not null, check)
    - Schema/SQL errors (undefined table/column)
    - Permission/auth errors
    - Programming errors
  """
  sqlstate = _extract_sqlstate(exc)

  # RETRYABLE: Serialization failure (common under SERIALIZABLE isolation)
  if sqlstate == "40001":
    return DBFailureClassification(retryable=True, reason="Serialization failure - transaction conflict", sqlstate=sqlstate, category="serialization_conflict")

  # RETRYABLE: Deadlock detected
  if sqlstate == "40P01":
    return DBFailureClassification(retryable=True, reason="Deadlock detected", sqlstate=sqlstate, category="deadlock")

  # MAYBE RETRYABLE: Lock not available (be conservative - don't retry by default)
  if sqlstate == "55P03":
    return DBFailureClassification(
      retryable=False,  # Too aggressive to retry lock contention
      reason="Lock not available (NOWAIT)",
      sqlstate=sqlstate,
      category="lock_timeout",
    )

  # MAYBE RETRYABLE: Query canceled (timeout) - usually indicates slow query, not transient
  if sqlstate == "57014":
    return DBFailureClassification(
      retryable=False,  # Query should be fixed, not retried
      reason="Query canceled (timeout)",
      sqlstate=sqlstate,
      category="query_timeout",
    )

  # NON-RETRYABLE: Integrity violations (class 23xxx)
  if sqlstate and sqlstate.startswith("23"):
    violation_types = {
      "23000": "integrity constraint violation",
      "23001": "restrict violation",
      "23502": "not null violation",
      "23503": "foreign key violation",
      "23505": "unique violation",
      "23514": "check constraint violation",
      "23P01": "exclusion constraint violation",
    }
    specific = violation_types.get(sqlstate, "integrity constraint violation")
    return DBFailureClassification(retryable=False, reason=f"Integrity violation: {specific}", sqlstate=sqlstate, category="integrity_error")

  # NON-RETRYABLE: Schema/SQL errors (class 42xxx)
  if sqlstate and sqlstate.startswith("42"):
    return DBFailureClassification(retryable=False, reason="Schema/SQL error (undefined table/column, syntax error)", sqlstate=sqlstate, category="schema_error")

  # NON-RETRYABLE: Permission errors (class 28xxx)
  if sqlstate and sqlstate.startswith("28"):
    return DBFailureClassification(retryable=False, reason="Authentication/permission error", sqlstate=sqlstate, category="permission_error")

  # Fallback to exception type analysis
  if isinstance(exc, IntegrityError):
    return DBFailureClassification(retryable=False, reason="Integrity constraint violation (detected by exception type)", sqlstate=sqlstate, category="integrity_error")

  # NON-RETRYABLE: Programming errors (AttributeError, TypeError, ValueError, etc.)
  if isinstance(exc, (AttributeError, TypeError, ValueError, KeyError, IndexError)):
    return DBFailureClassification(retryable=False, reason=f"Programming error: {type(exc).__name__}", sqlstate=sqlstate, category="programming_error")

  # RETRYABLE: Operational errors that might be transient connectivity
  if isinstance(exc, OperationalError):
    error_msg = str(exc).lower()
    # Check for connection-related issues
    if any(pattern in error_msg for pattern in ["connection", "timeout", "reset", "network", "broken pipe", "lost connection"]):
      return DBFailureClassification(retryable=True, reason="Transient connection/network error", sqlstate=sqlstate, category="connectivity_error")
    # Unknown operational error - be conservative
    return DBFailureClassification(retryable=False, reason="Operational error (unknown cause)", sqlstate=sqlstate, category="operational_error_unknown")

  # Default: Non-retryable for unknown errors
  return DBFailureClassification(retryable=False, reason=f"Unknown error type: {type(exc).__name__}", sqlstate=sqlstate, category="unknown_error")


async def execute_with_retry(*, operation_name: str, func: Any, max_attempts: int = 2, initial_backoff_ms: int = 100, max_backoff_ms: int = 2000, jitter: bool = True) -> Any:
  """
  Execute a database operation with retry logic for transient failures.

  Args:
    operation_name: Human-readable name for logging (e.g., "section_widget_creation")
    func: Async callable to execute (should be idempotent)
    max_attempts: Maximum number of attempts (initial + retries, default is 2: initial + 1 retry)
    initial_backoff_ms: Starting backoff delay in milliseconds
    max_backoff_ms: Maximum backoff delay in milliseconds
    jitter: Add randomness to backoff to avoid thundering herd

  Returns:
    Result from func

  Raises:
    Original exception if non-retryable or max retries exceeded
  """
  attempt = 0
  last_exception = None

  while attempt < max_attempts:
    attempt += 1

    try:
      result = await func()
      if attempt > 1:
        logger.info("DB operation succeeded after retry: operation=%s, attempt=%d/%d", operation_name, attempt, max_attempts)
      return result

    except Exception as exc:
      last_exception = exc
      classification = classify_db_failure(exc)

      # Log the failure with classification details
      logger.warning(
        "DB operation failed: operation=%s, attempt=%d/%d, category=%s, sqlstate=%s, retryable=%s, reason=%s",
        operation_name,
        attempt,
        max_attempts,
        classification.category,
        classification.sqlstate or "none",
        classification.retryable,
        classification.reason,
        exc_info=(not classification.retryable),  # Full traceback only for non-retryable
      )

      # Non-retryable error - fail fast
      if not classification.retryable:
        logger.error("DB operation failed with non-retryable error: operation=%s, category=%s, sqlstate=%s - failing immediately", operation_name, classification.category, classification.sqlstate or "none")
        raise

      # Retryable but out of attempts
      if attempt >= max_attempts:
        logger.error("DB operation failed after %d attempts: operation=%s, category=%s, sqlstate=%s - giving up", max_attempts, operation_name, classification.category, classification.sqlstate or "none")
        raise

      # Calculate backoff delay with exponential growth and optional jitter
      backoff_ms = min(initial_backoff_ms * (2 ** (attempt - 1)), max_backoff_ms)
      if jitter:
        # Add ±25% jitter to avoid thundering herd
        jitter_range = backoff_ms * 0.25
        backoff_ms += random.uniform(-jitter_range, jitter_range)

      logger.info("Retrying DB operation after backoff: operation=%s, attempt=%d/%d, backoff_ms=%.1f, category=%s", operation_name, attempt, max_attempts, backoff_ms, classification.category)

      # Wait before retry
      await asyncio.sleep(backoff_ms / 1000.0)

  # Should never reach here, but just in case
  if last_exception:
    raise last_exception
  raise RuntimeError(f"DB operation {operation_name} failed with no exception captured")
