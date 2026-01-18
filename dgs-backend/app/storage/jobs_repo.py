"""Storage interfaces for background jobs."""

from __future__ import annotations

from typing import Protocol

from app.jobs.models import JobRecord, JobStatus


class JobsRepository(Protocol):
  """Repository contract for job persistence."""

  def create_job(self, record: JobRecord) -> None:
    """Persist an initial job record."""

  def get_job(self, job_id: str) -> JobRecord | None:
    """Fetch a job by identifier."""

  def update_job(
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
    """Apply partial updates to a job."""

  def find_queued(self, limit: int = 5) -> list[JobRecord]:
    """Return a small batch of queued jobs."""

  def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
    """Return a job created with a given idempotency key, if present."""

  def list_jobs(self, limit: int, offset: int, status: str | None = None, job_id: str | None = None) -> tuple[list[JobRecord], int]:
    """Return a paginated list of jobs with optional filters, and total count."""
