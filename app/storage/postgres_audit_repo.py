"""Postgres-backed repository for LLM call audit records using SQLAlchemy."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import String, cast, func, select

from app.core.database import get_session_factory
from app.schema.audit import LlmCallAudit
from app.schema.fenster import FensterWidget
from app.schema.jobs import Job
from app.schema.lessons import Section

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmAuditRecord:
  """Store raw request/response details for a single LLM call."""

  record_id: int
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


@dataclass(frozen=True)
class LlmPricingRow:
  """Store LLM call details needed for pricing aggregation."""

  record_id: int
  started_at: datetime
  provider: str
  model: str
  prompt_tokens: int | None
  completion_tokens: int | None
  total_tokens: int | None
  status: str
  job_id: str | None
  lesson_id: str | None
  section_id: int | None
  illustration_id: int | None
  tutor_id: int | None
  fenster_id: str | None
  fenster_public_id: str | None


class PostgresLlmAuditRepository:
  """Persist LLM audit records into Postgres for later analysis using SQLAlchemy."""

  def __init__(self, table_name: str = "llm_call_audit") -> None:
    self._session_factory = get_session_factory()
    if self._session_factory is None:
      raise RuntimeError("Database not initialized")

  async def insert_record(self, record: LlmAuditRecord) -> int:
    """Insert an audit record."""
    async with self._session_factory() as session:
      audit = LlmCallAudit(
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
      await session.flush()
      await session.commit()
      logger.debug("Inserted LLM audit record %s", audit.id)
      return audit.id

  async def update_record(
    self, *, record_id: int, timestamp_response: datetime, response_payload: str | None, status: str, error_message: str | None, duration_ms: int, prompt_tokens: int | None, completion_tokens: int | None, total_tokens: int | None
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
    self,
    page: int = 1,
    limit: int = 20,
    job_id: str | None = None,
    agent: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    request_type: str | None = None,
    sort_by: str = "started_at",
    sort_order: str = "desc",
  ) -> tuple[list[LlmAuditRecord], int]:
    """Return a paginated list of LLM audit records with optional filters and sorting."""
    async with self._session_factory() as session:
      # Calculate offset from page
      offset = (page - 1) * limit

      # Build base query
      stmt = select(LlmCallAudit).limit(limit).offset(offset)
      count_stmt = select(func.count()).select_from(LlmCallAudit)

      # Apply filters
      conditions = []
      if job_id:
        conditions.append(LlmCallAudit.job_id == job_id)
      if agent:
        conditions.append(LlmCallAudit.agent == agent)
      if status:
        conditions.append(LlmCallAudit.status == status)
      if provider:
        conditions.append(LlmCallAudit.provider == provider)
      if model:
        conditions.append(LlmCallAudit.model == model)
      if request_type:
        conditions.append(LlmCallAudit.request_type == request_type)

      if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

      # Apply sorting
      sort_column = LlmCallAudit.started_at  # default
      if sort_by == "started_at":
        sort_column = LlmCallAudit.started_at
      elif sort_by == "duration_ms":
        sort_column = LlmCallAudit.duration_ms
      elif sort_by == "agent":
        sort_column = LlmCallAudit.agent
      elif sort_by == "provider":
        sort_column = LlmCallAudit.provider
      elif sort_by == "model":
        sort_column = LlmCallAudit.model
      elif sort_by == "status":
        sort_column = LlmCallAudit.status

      if sort_order.lower() == "asc":
        stmt = stmt.order_by(sort_column.asc())
      else:
        stmt = stmt.order_by(sort_column.desc())

      # Execute queries
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

  def _build_pricing_row(self, audit: LlmCallAudit, lesson_id: str | None, section_id: int | None, illustration_id: int | None, tutor_id: int | None, fenster_id: uuid.UUID | None, fenster_public_id: str | None) -> LlmPricingRow:
    """Normalize audit row data into pricing-friendly shape."""
    # Normalize nullable IDs to strings where needed.
    fenster_id_value = str(fenster_id) if fenster_id is not None else None
    fenster_public_value = str(fenster_public_id) if fenster_public_id is not None else None
    # Assemble payload to keep constructor calls short.
    row_payload = {
      "record_id": int(audit.id),
      "started_at": audit.started_at,
      "provider": audit.provider,
      "model": audit.model,
      "prompt_tokens": audit.prompt_tokens,
      "completion_tokens": audit.completion_tokens,
      "total_tokens": audit.total_tokens,
      "status": audit.status,
      "job_id": audit.job_id,
      "lesson_id": str(lesson_id) if lesson_id is not None else None,
      "section_id": int(section_id) if section_id is not None else None,
      "illustration_id": int(illustration_id) if illustration_id is not None else None,
      "tutor_id": int(tutor_id) if tutor_id is not None else None,
      "fenster_id": fenster_id_value,
      "fenster_public_id": fenster_public_value,
    }
    return LlmPricingRow(**row_payload)

  async def list_pricing_rows_for_target(self, *, target_type: str, target_id: str, start_at: datetime | None = None, end_at: datetime | None = None) -> list[LlmPricingRow]:
    """Return pricing rows filtered by a specific target id."""
    async with self._session_factory() as session:
      # Join related tables so target-specific filters can be applied.
      fenster_public_id = cast(Job.result_json["fenster_resource_id"].astext, String)
      select_columns = (LlmCallAudit, Job.lesson_id, Job.section_id, Section.illustration_id, Section.tutor_id, FensterWidget.fenster_id, FensterWidget.public_id)
      stmt = select(*select_columns)
      stmt = stmt.outerjoin(Job, Job.job_id == LlmCallAudit.job_id)
      stmt = stmt.outerjoin(Section, Section.section_id == Job.section_id)
      stmt = stmt.outerjoin(FensterWidget, FensterWidget.public_id == fenster_public_id)

      conditions = []
      if start_at is not None:
        conditions.append(LlmCallAudit.started_at >= start_at)

      if end_at is not None:
        conditions.append(LlmCallAudit.started_at <= end_at)

      normalized_type = str(target_type or "").strip().lower()
      # Map target type inputs to the correct filter columns.
      if normalized_type == "job":
        conditions.append(LlmCallAudit.job_id == target_id)
      elif normalized_type == "lesson":
        conditions.append(Job.lesson_id == target_id)
      elif normalized_type == "section":
        # Enforce integer ids for section filters.
        try:
          section_id = int(target_id)
        except ValueError as exc:
          raise ValueError("Invalid section id.") from exc

        conditions.append(Job.section_id == section_id)
      elif normalized_type == "illustration":
        # Enforce integer ids for illustration filters.
        try:
          illustration_id = int(target_id)
        except ValueError as exc:
          raise ValueError("Invalid illustration id.") from exc

        conditions.append(Section.illustration_id == illustration_id)
      elif normalized_type == "tutor":
        # Enforce integer ids for tutor filters.
        try:
          tutor_id = int(target_id)
        except ValueError as exc:
          raise ValueError("Invalid tutor id.") from exc

        conditions.append(Section.tutor_id == tutor_id)
      elif normalized_type == "fenster":
        # Accept fenster UUIDs or public ids for lookup.
        try:
          fenster_uuid = uuid.UUID(target_id)
        except ValueError:
          fenster_uuid = None

        if fenster_uuid is not None:
          conditions.append(FensterWidget.fenster_id == fenster_uuid)
        else:
          conditions.append(FensterWidget.public_id == target_id)
      else:
        raise ValueError("Unsupported pricing target type.")

      if conditions:
        stmt = stmt.where(*conditions)

      stmt = stmt.order_by(LlmCallAudit.started_at.desc())
      result = await session.execute(stmt)
      rows = result.all()

      pricing_rows: list[LlmPricingRow] = []
      for audit, lesson_id, section_id, illustration_id, tutor_id, fenster_id, fenster_public in rows:
        pricing_rows.append(self._build_pricing_row(audit, lesson_id, section_id, illustration_id, tutor_id, fenster_id, fenster_public))

      return pricing_rows

  async def list_pricing_rows_for_jobs(self, *, job_ids: list[str], start_at: datetime | None = None, end_at: datetime | None = None) -> list[LlmPricingRow]:
    """Return pricing rows for a set of job ids."""
    if not job_ids:
      return []

    async with self._session_factory() as session:
      # Join related tables so job-level totals can include artifact ids.
      fenster_public_id = cast(Job.result_json["fenster_resource_id"].astext, String)
      select_columns = (LlmCallAudit, Job.lesson_id, Job.section_id, Section.illustration_id, Section.tutor_id, FensterWidget.fenster_id, FensterWidget.public_id)
      stmt = select(*select_columns)
      stmt = stmt.outerjoin(Job, Job.job_id == LlmCallAudit.job_id)
      stmt = stmt.outerjoin(Section, Section.section_id == Job.section_id)
      stmt = stmt.outerjoin(FensterWidget, FensterWidget.public_id == fenster_public_id)

      # Apply job and time filters for the requested rows.
      conditions = [LlmCallAudit.job_id.in_(job_ids)]
      if start_at is not None:
        conditions.append(LlmCallAudit.started_at >= start_at)

      if end_at is not None:
        conditions.append(LlmCallAudit.started_at <= end_at)

      stmt = stmt.where(*conditions).order_by(LlmCallAudit.started_at.desc())
      result = await session.execute(stmt)
      rows = result.all()

      pricing_rows: list[LlmPricingRow] = []
      for audit, lesson_id, section_id, illustration_id, tutor_id, fenster_id, fenster_public in rows:
        pricing_rows.append(self._build_pricing_row(audit, lesson_id, section_id, illustration_id, tutor_id, fenster_id, fenster_public))

      return pricing_rows
