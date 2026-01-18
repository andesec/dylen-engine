"""Postgres-backed repository for LLM call audit records."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql


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
