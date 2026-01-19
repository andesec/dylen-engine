"""Postgres-backed repository for LLM call audit records using SQLAlchemy."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.schema.audit import LlmCallAudit

# The original file had it defined at the top. I should keep it there.

logger = logging.getLogger(__name__)

from dataclasses import dataclass

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
    """Persist LLM audit records into Postgres for later analysis using SQLAlchemy."""

    def __init__(self, table_name: str = "llm_call_audit") -> None:
        self._session_factory = get_session_factory()
        if self._session_factory is None:
             raise RuntimeError("Database not initialized")

    async def insert_record(self, record: LlmAuditRecord) -> None:
        """Insert an audit record."""
        async with self._session_factory() as session:
            audit = LlmCallAudit(
                id=record.record_id,
                timestamp_request=record.timestamp_request,
                timestamp_response=record.timestamp_response,
                started_at=record.started_at,
                duration_ms=record.duration_ms,
                agent=record.agent,
                provider=record.provider,
                model=record.model,
                lesson_topic=record.lesson_topic,
                request_payload=record.request_payload,
                response_payload=record.response_payload,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                total_tokens=record.total_tokens,
                request_type=record.request_type,
                purpose=record.purpose,
                call_index=record.call_index,
                job_id=record.job_id,
                status=record.status,
                error_message=record.error_message,
            )
            session.add(audit)
            await session.commit()
            logger.debug("Inserted LLM audit record %s", record.record_id)

    async def update_record(
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
        async with self._session_factory() as session:
            audit = await session.get(LlmCallAudit, record_id)
            if not audit:
                logger.warning("Attempted to update missing audit record %s", record_id)
                return

            audit.timestamp_response = timestamp_response
            audit.response_payload = response_payload
            audit.status = status
            audit.error_message = error_message
            audit.duration_ms = duration_ms
            audit.prompt_tokens = prompt_tokens
            audit.completion_tokens = completion_tokens
            audit.total_tokens = total_tokens

            await session.commit()
            logger.debug("Updated LLM audit record %s", record_id)

    async def list_records(
        self, limit: int, offset: int, job_id: str | None = None, agent: str | None = None, status: str | None = None
    ) -> tuple[list[LlmAuditRecord], int]:
        """Return a paginated list of LLM audit records with optional filters."""
        async with self._session_factory() as session:
            stmt = select(LlmCallAudit).order_by(LlmCallAudit.started_at.desc()).limit(limit).offset(offset)
            count_stmt = select(func.count()).select_from(LlmCallAudit)

            conditions = []
            if job_id:
                conditions.append(LlmCallAudit.job_id == job_id)
            if agent:
                conditions.append(LlmCallAudit.agent == agent)
            if status:
                conditions.append(LlmCallAudit.status == status)

            if conditions:
                stmt = stmt.where(*conditions)
                count_stmt = count_stmt.where(*conditions)

            total = await session.scalar(count_stmt)
            result = await session.execute(stmt)
            rows = result.scalars().all()

            records = []
            for row in rows:
                records.append(
                    LlmAuditRecord(
                        record_id=row.id,
                        timestamp_request=row.timestamp_request,
                        timestamp_response=row.timestamp_response,
                        started_at=row.started_at,
                        duration_ms=row.duration_ms,
                        agent=row.agent,
                        provider=row.provider,
                        model=row.model,
                        lesson_topic=row.lesson_topic,
                        request_payload=row.request_payload,
                        response_payload=row.response_payload,
                        prompt_tokens=row.prompt_tokens,
                        completion_tokens=row.completion_tokens,
                        total_tokens=row.total_tokens,
                        request_type=row.request_type,
                        purpose=row.purpose,
                        call_index=row.call_index,
                        job_id=row.job_id,
                        status=row.status,
                        error_message=row.error_message,
                    )
                )

            return records, (total or 0)
