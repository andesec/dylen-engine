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
        progress: float | None = None,
        logs: list[str] | None = None,
        result_json: dict | None = None,
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
