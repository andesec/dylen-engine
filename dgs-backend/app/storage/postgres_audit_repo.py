"""Postgres-backed repository for LLM call audit records."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


@dataclass(frozen=True)
class LlmAuditRecord:
  """Store raw request/response details for a single LLM call."""

  record_id: str
  timestamp_request: datetime
  timestamp_response: datetime | None
  started_at: datetime
  duration_ms: int
  agent: str
  provider: str
  model: str
  lesson_topic: str | None
  request_payload: str
  response_payload: str | None
  prompt_tokens: int | None
  completion_tokens: int | None
  total_tokens: int | None
  request_type: str
  purpose: str | None
  call_index: str | None
  job_id: str | None
  status: str
  error_message: str | None


class PostgresLlmAuditRepository:
  """Persist LLM audit records into Postgres for later analysis."""

  def __init__(self, *, dsn: str, connect_timeout: int) -> None:
    self._dsn = dsn
    self._connect_timeout = connect_timeout

  def insert_record(self, record: LlmAuditRecord) -> None:
    """Insert an audit record using a short-lived connection for safety."""
    statement = sql.SQL(
      """
            INSERT INTO llm_call_audit (
              id,
              timestamp_request,
              timestamp_response,
              started_at,
              duration_ms,
              agent,
              provider,
              model,
              lesson_topic,
              request_payload,
              response_payload,
              prompt_tokens,
              completion_tokens,
              total_tokens,
              request_type,
              purpose,
              call_index,
              job_id,
              status,
              error_message
            )
            VALUES (
              %(id)s,
              %(timestamp_request)s,
              %(timestamp_response)s,
              %(started_at)s,
              %(duration_ms)s,
              %(agent)s,
              %(provider)s,
              %(model)s,
              %(lesson_topic)s,
              %(request_payload)s,
              %(response_payload)s,
              %(prompt_tokens)s,
              %(completion_tokens)s,
              %(total_tokens)s,
              %(request_type)s,
              %(purpose)s,
              %(call_index)s,
              %(job_id)s,
              %(status)s,
              %(error_message)s
            )
            """
    )
    payload: dict[str, Any] = {
      "id": record.record_id,
      "timestamp_request": record.timestamp_request,
      "timestamp_response": record.timestamp_response,
      "started_at": record.started_at,
      "duration_ms": record.duration_ms,
      "agent": record.agent,
      "provider": record.provider,
      "model": record.model,
      "lesson_topic": record.lesson_topic,
      "request_payload": record.request_payload,
      "response_payload": record.response_payload,
      "prompt_tokens": record.prompt_tokens,
      "completion_tokens": record.completion_tokens,
      "total_tokens": record.total_tokens,
      "request_type": record.request_type,
      "purpose": record.purpose,
      "call_index": record.call_index,
      "job_id": record.job_id,
      "status": record.status,
      "error_message": record.error_message,
    }
    logger = logging.getLogger(__name__)

    # Open a short-lived connection to keep async usage safe and predictable.

    with psycopg.connect(self._dsn, connect_timeout=self._connect_timeout) as conn:
      with conn.cursor() as cursor:
        cursor.execute(statement, payload)

    logger.debug("Inserted LLM audit record %s", record.record_id)

  def update_record(
    self,
    *,
    record_id: str,
    timestamp_response: datetime,
    response_payload: str | None,
    status: str,
    error_message: str | None,
    duration_ms: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None,
  ) -> None:
    """Update an existing audit record after the LLM call completes."""
    statement = sql.SQL(
      """
            UPDATE llm_call_audit
            SET
              timestamp_response = %(timestamp_response)s,
              response_payload = %(response_payload)s,
              status = %(status)s,
              error_message = %(error_message)s,
              duration_ms = %(duration_ms)s,
              prompt_tokens = %(prompt_tokens)s,
              completion_tokens = %(completion_tokens)s,
              total_tokens = %(total_tokens)s
            WHERE id = %(id)s
            """
    )
    payload: dict[str, Any] = {
      "id": record_id,
      "timestamp_response": timestamp_response,
      "response_payload": response_payload,
      "status": status,
      "error_message": error_message,
      "duration_ms": duration_ms,
      "prompt_tokens": prompt_tokens,
      "completion_tokens": completion_tokens,
      "total_tokens": total_tokens,
    }
    logger = logging.getLogger(__name__)

    # Open a short-lived connection to keep async usage safe and predictable.

    with psycopg.connect(self._dsn, connect_timeout=self._connect_timeout) as conn:
      with conn.cursor() as cursor:
        cursor.execute(statement, payload)

    logger.debug("Updated LLM audit record %s", record_id)

  def list_records(self, limit: int, offset: int, job_id: str | None = None, agent: str | None = None, status: str | None = None) -> tuple[list[LlmAuditRecord], int]:
    """Return a paginated list of LLM audit records with optional filters."""
    where_clauses = []
    params = {}

    if job_id:
      where_clauses.append("job_id = %(job_id)s")
      params["job_id"] = job_id

    if agent:
      where_clauses.append("agent = %(agent)s")
      params["agent"] = agent

    if status:
      where_clauses.append("status = %(status)s")
      params["status"] = status

    where_sql = sql.SQL(" WHERE " if where_clauses else "") + sql.SQL(" AND ").join([sql.SQL(c) for c in where_clauses])

    count_query = sql.SQL("SELECT COUNT(*) FROM llm_call_audit") + where_sql

    items_query = sql.SQL("SELECT * FROM llm_call_audit") + where_sql + sql.SQL(" ORDER BY started_at DESC LIMIT %(limit)s OFFSET %(offset)s")
    params["limit"] = limit
    params["offset"] = offset

    with psycopg.connect(self._dsn, connect_timeout=self._connect_timeout) as conn:
      with conn.cursor() as cursor:
        cursor.execute(count_query, params)
        total = cursor.fetchone()[0]

      with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(items_query, params)
        rows = cursor.fetchall()

    records = []
    for row in rows:
      # Map row to LlmAuditRecord
      payload = {
        "record_id": row["id"],
        "timestamp_request": row["timestamp_request"],
        "timestamp_response": row.get("timestamp_response"),
        "started_at": row["started_at"],
        "duration_ms": row["duration_ms"],
        "agent": row["agent"],
        "provider": row["provider"],
        "model": row["model"],
        "lesson_topic": row.get("lesson_topic"),
        "request_payload": row["request_payload"],
        "response_payload": row.get("response_payload"),
        "prompt_tokens": row.get("prompt_tokens"),
        "completion_tokens": row.get("completion_tokens"),
        "total_tokens": row.get("total_tokens"),
        "request_type": row["request_type"],
        "purpose": row.get("purpose"),
        "call_index": row.get("call_index"),
        "job_id": row.get("job_id"),
        "status": row["status"],
        "error_message": row.get("error_message"),
      }
      records.append(LlmAuditRecord(**payload))

    return records, total
