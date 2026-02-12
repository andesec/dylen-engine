"""Postgres-backed repository for background jobs using SQLAlchemy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_factory
from app.jobs.models import JobKind, JobRecord, JobStatus
from app.schema.jobs import Job, JobCheckpoint, JobEvent
from app.storage.jobs_repo import JobCheckpointRecord, JobsRepository


def _now_iso() -> str:
  return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class PostgresJobsRepository(JobsRepository):
  """Persist jobs/checkpoints/events to Postgres using SQLAlchemy."""

  def __init__(self, table_name: str = "jobs") -> None:
    _ = table_name
    self._session_factory = get_session_factory()
    if self._session_factory is None:
      raise RuntimeError("Database not initialized")

  async def create_job(self, record: JobRecord) -> None:
    async with self._session_factory() as session:
      job = Job(
        job_id=record.job_id,
        root_job_id=str(record.root_job_id or record.job_id),
        resume_source_job_id=record.resume_source_job_id,
        superseded_by_job_id=record.superseded_by_job_id,
        user_id=record.user_id,
        job_kind=record.job_kind,
        request_json=record.request,
        status=record.status,
        parent_job_id=record.parent_job_id,
        lesson_id=record.lesson_id,
        section_id=record.section_id,
        target_agent=record.target_agent,
        result_json=record.result_json,
        error_json=record.error_json,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        idempotency_key=str(record.idempotency_key or f"{record.job_id}:{record.job_kind}"),
      )
      session.add(job)
      await session.commit()
      if record.logs:
        await self._append_events_in_session(session=session, job_id=record.job_id, event_type="log", messages=record.logs)
        await session.commit()

  async def get_job(self, job_id: str) -> JobRecord | None:
    async with self._session_factory() as session:
      row = await session.get(Job, job_id)
      if row is None:
        return None
      logs = await self._list_event_messages_in_session(session=session, job_id=row.job_id, limit=100)
      return self._model_to_record(row, logs=logs)

  async def update_job(  # pylint: disable=too-many-arguments
    self,
    job_id: str,
    *,
    root_job_id: str | None = None,
    parent_job_id: str | None = None,
    resume_source_job_id: str | None = None,
    superseded_by_job_id: str | None = None,
    lesson_id: str | None = None,
    section_id: int | None = None,
    target_agent: str | None = None,
    job_kind: JobKind | None = None,
    status: JobStatus | None = None,
    phase: str | None = None,
    subphase: str | None = None,
    expected_sections: int | None = None,
    completed_sections: int | None = None,
    completed_section_indexes: list[int] | None = None,
    current_section_index: int | None = None,
    current_section_status: str | None = None,
    current_section_retry_count: int | None = None,
    current_section_title: str | None = None,
    retry_count: int | None = None,
    max_retries: int | None = None,
    retry_sections: list[int] | None = None,
    retry_agents: list[str] | None = None,
    retry_parent_job_id: str | None = None,
    total_steps: int | None = None,
    completed_steps: int | None = None,
    progress: float | None = None,
    request: dict | None = None,
    result_json: dict | None = None,
    error_json: dict | None = None,
    logs: list[str] | None = None,
    artifacts: dict | None = None,
    validation: dict | None = None,
    cost: dict | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
    updated_at: str | None = None,
  ) -> JobRecord | None:
    async with self._session_factory() as session:
      row = await session.get(Job, job_id)
      if row is None:
        return None
      if root_job_id is not None:
        row.root_job_id = root_job_id
      if parent_job_id is not None:
        row.parent_job_id = parent_job_id
      if resume_source_job_id is not None:
        row.resume_source_job_id = resume_source_job_id
      if superseded_by_job_id is not None:
        row.superseded_by_job_id = superseded_by_job_id
      if lesson_id is not None:
        row.lesson_id = lesson_id
      if section_id is not None:
        row.section_id = section_id
      if target_agent is not None:
        row.target_agent = target_agent
      if job_kind is not None:
        row.job_kind = job_kind
      if status is not None:
        row.status = status
      _ = (
        phase,
        subphase,
        expected_sections,
        completed_sections,
        completed_section_indexes,
        current_section_index,
        current_section_status,
        current_section_retry_count,
        current_section_title,
        retry_count,
        max_retries,
        retry_sections,
        retry_agents,
        retry_parent_job_id,
        total_steps,
        completed_steps,
        progress,
        artifacts,
        validation,
        cost,
      )
      if request is not None:
        row.request_json = request
      if result_json is not None:
        row.result_json = result_json
      if error_json is not None:
        row.error_json = error_json
      if started_at is not None:
        row.started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
      if completed_at is not None:
        row.completed_at = completed_at
      row.updated_at = updated_at or _now_iso()
      session.add(row)
      await session.flush()
      if logs:
        await self._append_events_in_session(session=session, job_id=job_id, event_type="log", messages=logs)
      await session.commit()
      await session.refresh(row)
      logs_snapshot = await self._list_event_messages_in_session(session=session, job_id=row.job_id, limit=100)
      return self._model_to_record(row, logs=logs_snapshot)

  async def find_queued(self, limit: int = 5) -> list[JobRecord]:
    async with self._session_factory() as session:
      stmt = select(Job).where(Job.status == "queued").order_by(Job.created_at.asc()).limit(limit)
      rows = (await session.execute(stmt)).scalars().all()
      result: list[JobRecord] = []
      for row in rows:
        logs = await self._list_event_messages_in_session(session=session, job_id=row.job_id, limit=100)
        result.append(self._model_to_record(row, logs=logs))
      return result

  async def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
    async with self._session_factory() as session:
      stmt = select(Job).where(Job.idempotency_key == idempotency_key).order_by(Job.created_at.asc()).limit(1)
      row = (await session.execute(stmt)).scalar_one_or_none()
      if row is None:
        return None
      logs = await self._list_event_messages_in_session(session=session, job_id=row.job_id, limit=100)
      return self._model_to_record(row, logs=logs)

  async def find_by_user_kind_idempotency_key(self, *, user_id: str | None, job_kind: JobKind, idempotency_key: str) -> JobRecord | None:
    async with self._session_factory() as session:
      stmt = select(Job).where(Job.user_id == user_id, Job.job_kind == job_kind, Job.idempotency_key == idempotency_key).order_by(Job.created_at.asc()).limit(1)
      row = (await session.execute(stmt)).scalar_one_or_none()
      if row is None:
        return None
      logs = await self._list_event_messages_in_session(session=session, job_id=row.job_id, limit=100)
      return self._model_to_record(row, logs=logs)

  async def list_child_jobs(self, *, parent_job_id: str, include_done: bool = False) -> list[JobRecord]:
    async with self._session_factory() as session:
      stmt = select(Job).where(Job.parent_job_id == parent_job_id).order_by(Job.created_at.asc())
      if not include_done:
        stmt = stmt.where(Job.status != "done")
      rows = (await session.execute(stmt)).scalars().all()
      result: list[JobRecord] = []
      for row in rows:
        logs = await self._list_event_messages_in_session(session=session, job_id=row.job_id, limit=100)
        result.append(self._model_to_record(row, logs=logs))
      return result

  async def list_jobs(
    self, page: int = 1, limit: int = 20, status: str | None = None, job_id: str | None = None, job_kind: str | None = None, user_id: str | None = None, target_agent: str | None = None, sort_by: str = "created_at", sort_order: str = "desc"
  ) -> tuple[list[JobRecord], int]:
    async with self._session_factory() as session:
      offset = (page - 1) * limit
      stmt = select(Job).limit(limit).offset(offset)
      count_stmt = select(func.count()).select_from(Job)
      filters = []
      if status:
        filters.append(Job.status == status)
      if job_id:
        filters.append(or_(Job.job_id == job_id, Job.root_job_id == job_id))
      if job_kind:
        filters.append(Job.job_kind == job_kind)
      if user_id:
        filters.append(Job.user_id == user_id)
      if target_agent:
        filters.append(Job.target_agent == target_agent)
      if filters:
        stmt = stmt.where(and_(*filters))
        count_stmt = count_stmt.where(and_(*filters))
      sort_column = Job.created_at
      if sort_by == "job_id":
        sort_column = Job.job_id
      elif sort_by == "updated_at":
        sort_column = Job.updated_at
      elif sort_by == "status":
        sort_column = Job.status
      elif sort_by == "job_kind":
        sort_column = Job.job_kind
      stmt = stmt.order_by(sort_column.asc() if sort_order.lower() == "asc" else sort_column.desc())
      total = await session.scalar(count_stmt)
      rows = (await session.execute(stmt)).scalars().all()
      items: list[JobRecord] = []
      for row in rows:
        logs = await self._list_event_messages_in_session(session=session, job_id=row.job_id, limit=100)
        items.append(self._model_to_record(row, logs=logs))
      return items, int(total or 0)

  async def append_event(self, *, job_id: str, event_type: str, message: str, payload_json: dict | None = None) -> None:
    async with self._session_factory() as session:
      session.add(JobEvent(job_id=job_id, event_type=event_type, message=message, payload_json=payload_json))
      await session.commit()

  async def list_events(self, *, job_id: str, limit: int = 100) -> list[str]:
    async with self._session_factory() as session:
      return await self._list_event_messages_in_session(session=session, job_id=job_id, limit=limit)

  async def claim_checkpoint(self, *, job_id: str, stage: str, section_index: int | None) -> JobCheckpointRecord | None:
    async with self._session_factory() as session:
      stmt = select(JobCheckpoint).where(*self._checkpoint_key_filters(job_id=job_id, stage=stage, section_index=section_index), JobCheckpoint.state.in_(("pending", "error"))).with_for_update(skip_locked=True).limit(1)
      row = (await session.execute(stmt)).scalar_one_or_none()
      if row is None:
        return None
      row.state = "running"
      session.add(row)
      await session.commit()
      await session.refresh(row)
      return self._checkpoint_to_record(row)

  async def upsert_checkpoint(self, *, job_id: str, stage: str, section_index: int | None, state: str, artifact_refs_json: dict | None = None, attempt_count: int | None = None, last_error: str | None = None) -> JobCheckpointRecord:
    async with self._session_factory() as session:
      row = await self._upsert_checkpoint_in_session(session=session, job_id=job_id, stage=stage, section_index=section_index, state=state, artifact_refs_json=artifact_refs_json, attempt_count=attempt_count, last_error=last_error)
      return self._checkpoint_to_record(row)

  async def get_checkpoint(self, *, job_id: str, stage: str, section_index: int | None) -> JobCheckpointRecord | None:
    async with self._session_factory() as session:
      stmt = select(JobCheckpoint).where(*self._checkpoint_key_filters(job_id=job_id, stage=stage, section_index=section_index)).limit(1)
      row = (await session.execute(stmt)).scalar_one_or_none()
      if row is None:
        return None
      return self._checkpoint_to_record(row)

  def _checkpoint_key_filters(self, *, job_id: str, stage: str, section_index: int | None) -> tuple[Any, ...]:
    if section_index is None:
      return (JobCheckpoint.job_id == job_id, JobCheckpoint.stage == stage, JobCheckpoint.section_index.is_(None))
    return (JobCheckpoint.job_id == job_id, JobCheckpoint.stage == stage, JobCheckpoint.section_index == section_index)

  async def _upsert_checkpoint_in_session(self, *, session: AsyncSession, job_id: str, stage: str, section_index: int | None, state: str, artifact_refs_json: dict | None, attempt_count: int | None, last_error: str | None) -> JobCheckpoint:
    stmt = select(JobCheckpoint).where(*self._checkpoint_key_filters(job_id=job_id, stage=stage, section_index=section_index)).limit(1)
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
      row = JobCheckpoint(job_id=job_id, stage=stage, section_index=section_index, state=state, artifact_refs_json=artifact_refs_json, attempt_count=int(attempt_count or 0), last_error=last_error)
      session.add(row)
    else:
      row.state = state
      if artifact_refs_json is not None:
        row.artifact_refs_json = artifact_refs_json
      if attempt_count is not None:
        row.attempt_count = int(attempt_count)
      if last_error is not None:
        row.last_error = last_error
      session.add(row)
    try:
      await session.commit()
    except IntegrityError:
      await session.rollback()
      row = (await session.execute(stmt)).scalar_one_or_none()
      if row is None:
        raise
      row.state = state
      if artifact_refs_json is not None:
        row.artifact_refs_json = artifact_refs_json
      if attempt_count is not None:
        row.attempt_count = int(attempt_count)
      if last_error is not None:
        row.last_error = last_error
      session.add(row)
      await session.commit()
    await session.refresh(row)
    return row

  async def list_checkpoints(self, *, job_id: str) -> list[JobCheckpointRecord]:
    async with self._session_factory() as session:
      stmt = select(JobCheckpoint).where(JobCheckpoint.job_id == job_id).order_by(JobCheckpoint.stage.asc(), JobCheckpoint.section_index.asc())
      rows = (await session.execute(stmt)).scalars().all()
      return [self._checkpoint_to_record(row) for row in rows]

  async def _append_events_in_session(self, *, session: AsyncSession, job_id: str, event_type: str, messages: list[str]) -> None:
    for message in messages:
      if str(message).strip() == "":
        continue
      session.add(JobEvent(job_id=job_id, event_type=event_type, message=str(message), payload_json=None))

  async def _list_event_messages_in_session(self, *, session: AsyncSession, job_id: str, limit: int) -> list[str]:
    stmt = select(JobEvent.message).where(JobEvent.job_id == job_id).order_by(JobEvent.created_at.desc(), JobEvent.id.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    ordered = list(reversed([str(item) for item in rows]))
    return ordered

  def _checkpoint_to_record(self, row: JobCheckpoint) -> JobCheckpointRecord:
    return JobCheckpointRecord(
      id=int(row.id),
      job_id=str(row.job_id),
      stage=str(row.stage),
      section_index=int(row.section_index) if row.section_index is not None else None,
      state=str(row.state),
      artifact_refs_json=row.artifact_refs_json,
      attempt_count=int(row.attempt_count),
      last_error=row.last_error,
    )

  def _model_to_record(self, row: Job, *, logs: list[str]) -> JobRecord:
    return JobRecord(
      job_id=row.job_id,
      root_job_id=row.root_job_id,
      user_id=row.user_id,
      job_kind=row.job_kind,
      request=row.request_json,
      status=row.status,
      created_at=row.created_at,
      updated_at=row.updated_at,
      parent_job_id=row.parent_job_id,
      resume_source_job_id=row.resume_source_job_id,
      superseded_by_job_id=row.superseded_by_job_id,
      lesson_id=row.lesson_id,
      section_id=row.section_id,
      target_agent=row.target_agent,
      logs=logs,
      result_json=row.result_json,
      error_json=row.error_json,
      started_at=row.started_at.isoformat() if row.started_at is not None else None,
      completed_at=row.completed_at,
      idempotency_key=row.idempotency_key,
    )
