from __future__ import annotations

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.jobs.models import JobRecord

# Ensure required settings are available before importing the app.
os.environ.setdefault("DGS_DEV_KEY", "test-key")
os.environ.setdefault("DGS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("DGS_JOBS_AUTO_PROCESS", "0")

from app.main import app


class InMemoryJobsRepo:
  """In-memory jobs repository for retry endpoint tests."""

  def __init__(self) -> None:
    self._jobs: dict[str, JobRecord] = {}

  def create_job(self, record: JobRecord) -> None:
    self._jobs[record.job_id] = record

  def get_job(self, job_id: str) -> JobRecord | None:
    return self._jobs.get(job_id)

  def update_job(self, job_id: str, **kwargs: object) -> JobRecord | None:
    record = self._jobs.get(job_id)

    # Bail out when the job id is unknown.
    if record is None:
      return None

    # Apply partial updates to mimic repository behavior.
    updated = replace(record, **{key: value for key, value in kwargs.items() if value is not None})
    self._jobs[job_id] = updated
    return updated

  def find_queued(self, limit: int = 5) -> list[JobRecord]:
    return []

  def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
    return None


def test_retry_job_requeues_failed_job(monkeypatch: pytest.MonkeyPatch) -> None:
  """Verify failed jobs can be retried with section/agent targeting."""
  # Seed a failed job record that is eligible for retries.
  repo = InMemoryJobsRepo()
  record = JobRecord(
    job_id="job-retry-1",
    request={"topic": "Retry test", "depth": "highlights"},
    status="error",
    phase="failed",
    expected_sections=2,
    completed_sections=1,
    completed_section_indexes=[0],
    retry_count=0,
    max_retries=2,
    created_at="2024-01-01T00:00:00Z",
    updated_at="2024-01-01T00:00:00Z",
    logs=["Job failed earlier."],
  )
  # Persist the job so the API handler can find it.
  repo.create_job(record)

  def _fake_repo(_settings: object) -> InMemoryJobsRepo:
    return repo

  # Replace the repository dependency with the in-memory test double.
  monkeypatch.setattr("app.main._get_jobs_repo", _fake_repo)
  client = TestClient(app)
  headers = {"X-DGS-Dev-Key": "test-key"}
  payload = {"sections": [1], "agents": ["structurer"]}
  # Invoke the retry endpoint with section/agent targeting.
  response = client.post("/v1/jobs/job-retry-1/retry", json=payload, headers=headers)
  assert response.status_code == 200
  body = response.json()
  assert body["status"] == "queued"
  assert body["retry_count"] == 1
  assert body["retry_sections"] == [1]
  assert body["retry_agents"] == ["structurer"]
