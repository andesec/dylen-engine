"""Storage interfaces for background jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.jobs.models import JobKind, JobRecord, JobStatus


@dataclass(frozen=True)
class JobCheckpointRecord:
  """Checkpoint row describing resumable stage progress."""

  id: int
  job_id: str
  stage: str
  section_index: int | None
  state: str
  artifact_refs_json: dict | None
  attempt_count: int
  last_error: str | None


class JobsRepository(Protocol):
  """Repository contract for job persistence."""

  async def create_job(self, record: JobRecord) -> None:
    """Persist an initial job record."""

  async def get_job(self, job_id: str) -> JobRecord | None:
    """Fetch a job by identifier."""

  async def update_job(
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
    """Apply partial updates to a job."""

  async def find_queued(self, limit: int = 5) -> list[JobRecord]:
    """Return a small batch of queued jobs."""

  async def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
    """Return a job created with a given idempotency key, if present."""

  async def find_by_user_kind_idempotency_key(self, *, user_id: str | None, job_kind: JobKind, idempotency_key: str) -> JobRecord | None:
    """Return a job created with a given (user, kind, idempotency_key) tuple."""

  async def list_child_jobs(self, *, parent_job_id: str, include_done: bool = False) -> list[JobRecord]:
    """Return direct child jobs for a parent job."""

  async def list_jobs(self, limit: int, offset: int, status: str | None = None, job_id: str | None = None) -> tuple[list[JobRecord], int]:
    """Return a paginated list of jobs with optional filters, and total count."""

  async def append_event(self, *, job_id: str, event_type: str, message: str, payload_json: dict | None = None) -> None:
    """Append one timeline event for a job."""

  async def list_events(self, *, job_id: str, limit: int = 100) -> list[str]:
    """List recent event messages for a job."""

  async def claim_checkpoint(self, *, job_id: str, stage: str, section_index: int | None) -> JobCheckpointRecord | None:
    """Atomically claim a checkpoint row for processing."""

  async def upsert_checkpoint(self, *, job_id: str, stage: str, section_index: int | None, state: str, artifact_refs_json: dict | None = None, attempt_count: int | None = None, last_error: str | None = None) -> JobCheckpointRecord:
    """Insert or update a checkpoint row."""

  async def get_checkpoint(self, *, job_id: str, stage: str, section_index: int | None) -> JobCheckpointRecord | None:
    """Get one checkpoint by logical key."""

  async def list_checkpoints(self, *, job_id: str) -> list[JobCheckpointRecord]:
    """List checkpoints for one job."""
