"""Postgres-backed repository for background jobs using SQLAlchemy."""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.core.database import get_session_factory
from app.jobs.guardrails import maybe_truncate_artifacts, maybe_truncate_result_json, sanitize_logs
from app.jobs.models import JobRecord, JobStatus
from app.schema.jobs import Job
from app.storage.jobs_repo import JobsRepository

logger = logging.getLogger(__name__)


class PostgresJobsRepository(JobsRepository):
  """Persist jobs to Postgres using SQLAlchemy."""

  def __init__(self, table_name: str = "dylen_jobs") -> None:
    self._session_factory = get_session_factory()
    if self._session_factory is None:
      raise RuntimeError("Database not initialized")

  async def create_job(self, record: JobRecord) -> None:
    """Insert a new job record."""
    async with self._session_factory() as session:
      # Apply guardrails
      safe_logs = sanitize_logs(record.logs)
      safe_result = maybe_truncate_result_json(record.result_json)
      safe_artifacts = maybe_truncate_artifacts(record.artifacts)

      job = Job(
        job_id=record.job_id,
        request=record.request,
        status=record.status,
        target_agent=record.target_agent,
        phase=record.phase,
        subphase=record.subphase,
        expected_sections=record.expected_sections,
        completed_sections=record.completed_sections,
        completed_section_indexes=record.completed_section_indexes,
        current_section_index=record.current_section_index,
        current_section_status=record.current_section_status,
        current_section_retry_count=record.current_section_retry_count,
        current_section_title=record.current_section_title,
        retry_count=record.retry_count,
        max_retries=record.max_retries,
        retry_sections=record.retry_sections,
        retry_agents=record.retry_agents,
        retry_parent_job_id=record.retry_parent_job_id,
        total_steps=record.total_steps,
        completed_steps=record.completed_steps,
        progress=record.progress,
        logs=safe_logs,
        result_json=safe_result,
        artifacts=safe_artifacts,
        validation=record.validation,
        cost=record.cost,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
        ttl=record.ttl,
        idempotency_key=record.idempotency_key,
      )
      session.add(job)
      await session.commit()

  async def get_job(self, job_id: str) -> JobRecord | None:
    """Fetch a job record by identifier."""
    async with self._session_factory() as session:
      job = await session.get(Job, job_id)
      if not job:
        return None
      return self._model_to_record(job)

  async def update_job(  # pylint: disable=too-many-arguments
    self,
    job_id: str,
    *,
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
    logs: list[str] | None = None,
    result_json: dict | None = None,
    artifacts: dict | None = None,
    validation: dict | None = None,
    cost: dict | None = None,
    completed_at: str | None = None,
    updated_at: str | None = None,
  ) -> JobRecord | None:
    """Apply partial updates to a job record."""
    async with self._session_factory() as session:
      job = await session.get(Job, job_id)
      if not job:
        return None

      # Preserve canceled status check from original repo
      if job.status == "canceled" and status is not None and status != "canceled":
        return self._model_to_record(job)

      # Update fields if provided
      if status is not None:
        job.status = status
      if phase is not None:
        job.phase = phase
      if subphase is not None:
        job.subphase = subphase
      if expected_sections is not None:
        job.expected_sections = expected_sections
      if completed_sections is not None:
        job.completed_sections = completed_sections
      if completed_section_indexes is not None:
        job.completed_section_indexes = completed_section_indexes
      if current_section_index is not None:
        job.current_section_index = current_section_index
      if current_section_status is not None:
        job.current_section_status = current_section_status
      if current_section_retry_count is not None:
        job.current_section_retry_count = current_section_retry_count
      if current_section_title is not None:
        job.current_section_title = current_section_title
      if retry_count is not None:
        job.retry_count = retry_count
      if max_retries is not None:
        job.max_retries = max_retries
      if retry_sections is not None:
        job.retry_sections = retry_sections
      if retry_agents is not None:
        job.retry_agents = retry_agents
      if retry_parent_job_id is not None:
        job.retry_parent_job_id = retry_parent_job_id
      if total_steps is not None:
        job.total_steps = total_steps
      if completed_steps is not None:
        job.completed_steps = completed_steps
      if progress is not None:
        job.progress = progress
      if logs is not None:
        job.logs = sanitize_logs(logs)
      if result_json is not None:
        job.result_json = maybe_truncate_result_json(result_json)
      if artifacts is not None:
        job.artifacts = maybe_truncate_artifacts(artifacts)
      if validation is not None:
        job.validation = validation
      if cost is not None:
        job.cost = cost
      if completed_at is not None:
        job.completed_at = completed_at

      # Always update updated_at (generating new timestamp if provided, or could rely on caller)
      # The original repo used `updated_at or _now_iso()`.
      # We assume the caller passes it, or we could generate it.
      # Typically logic layer handles this, but repo did it.
      if updated_at is not None:
        job.updated_at = updated_at
      else:
        from datetime import UTC, datetime

        job.updated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

      await session.commit()
      await session.refresh(job)
      return self._model_to_record(job)

  async def find_queued(self, limit: int = 5) -> list[JobRecord]:
    """Return a batch of queued jobs."""
    async with self._session_factory() as session:
      stmt = select(Job).where(Job.status == "queued").order_by(Job.created_at.asc()).limit(limit)
      result = await session.execute(stmt)
      jobs = result.scalars().all()
      return [self._model_to_record(j) for j in jobs]

  async def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
    """Find a job matching a given idempotency key."""
    async with self._session_factory() as session:
      stmt = select(Job).where(Job.idempotency_key == idempotency_key).order_by(Job.created_at.asc()).limit(1)
      result = await session.execute(stmt)
      job = result.scalar_one_or_none()
      if not job:
        return None
      return self._model_to_record(job)

  async def list_jobs(self, limit: int, offset: int, status: str | None = None, job_id: str | None = None) -> tuple[list[JobRecord], int]:
    """Return a paginated list of jobs with filters and total count."""
    async with self._session_factory() as session:
      stmt = select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
      count_stmt = select(func.count()).select_from(Job)

      conditions = []
      if status:
        conditions.append(Job.status == status)
      if job_id:
        conditions.append(Job.job_id == job_id)

      if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

      total = await session.scalar(count_stmt)
      result = await session.execute(stmt)
      jobs = result.scalars().all()

      return [self._model_to_record(j) for j in jobs], (total or 0)

  def _model_to_record(self, job: Job) -> JobRecord:
    """Convert a SQLAlchemy model to a domain record."""
    return JobRecord(
      job_id=job.job_id,
      request=job.request,
      status=job.status,
      target_agent=job.target_agent,
      phase=job.phase,
      subphase=job.subphase,
      expected_sections=job.expected_sections,
      completed_sections=job.completed_sections,
      completed_section_indexes=job.completed_section_indexes,
      current_section_index=job.current_section_index,
      current_section_status=job.current_section_status,
      current_section_retry_count=job.current_section_retry_count,
      current_section_title=job.current_section_title,
      retry_count=job.retry_count,
      max_retries=job.max_retries,
      retry_sections=job.retry_sections,
      retry_agents=job.retry_agents,
      retry_parent_job_id=job.retry_parent_job_id,
      total_steps=job.total_steps,
      completed_steps=job.completed_steps,
      progress=job.progress,
      logs=job.logs,
      result_json=job.result_json,
      artifacts=job.artifacts,
      validation=job.validation,
      cost=job.cost,
      created_at=job.created_at,
      updated_at=job.updated_at,
      completed_at=job.completed_at,
      ttl=job.ttl,
      idempotency_key=job.idempotency_key,
    )
