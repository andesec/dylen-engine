from __future__ import annotations

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.jobs.models import JobRecord

# Ensure required settings are available before importing the app.
os.environ["DGS_ALLOWED_ORIGINS"] = "http://localhost"
os.environ["DGS_JOBS_AUTO_PROCESS"] = "0"

from app.core.security import get_current_active_user  # noqa: E402
from app.main import app  # noqa: E402
from app.schema.sql import User  # noqa: E402


class InMemoryJobsRepo:
  """In-memory jobs repository for retry endpoint tests."""

  def __init__(self) -> None:
    self._jobs: dict[str, JobRecord] = {}

  async def create_job(self, record: JobRecord) -> None:
    self._jobs[record.job_id] = record

  async def get_job(self, job_id: str) -> JobRecord | None:
    return self._jobs.get(job_id)

  async def update_job(self, job_id: str, **kwargs: object) -> JobRecord | None:
    record = self._jobs.get(job_id)

    # Bail out when the job id is unknown.
    if record is None:
      return None

    # Apply partial updates to mimic repository behavior.
    updated = replace(record, **{key: value for key, value in kwargs.items() if value is not None})
    self._jobs[job_id] = updated
    return updated

  async def find_queued(self, limit: int = 5) -> list[JobRecord]:
    return []

  async def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
    return None


@pytest.mark.anyio
async def test_retry_job_requeues_failed_job(monkeypatch: pytest.MonkeyPatch) -> None:
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
  await repo.create_job(record)

  def _fake_repo(_settings: object) -> InMemoryJobsRepo:
    return repo

  # Replace the repository dependency with the in-memory test double.
  monkeypatch.setattr("app.services.jobs._get_jobs_repo", _fake_repo)

  # Override get_settings to ensure settings are correct.
  from app.config import get_settings

  # We can just use the real get_settings since env vars are set at module level
  # But to be safe and avoid cached values:
  def _get_settings_override():
    return get_settings.__wrapped__()

  app.dependency_overrides[get_settings] = _get_settings_override

  # Override auth to bypass security
  def _get_current_active_user_override():
    return User(id="test-user-id", email="test@example.com", is_approved=True)

  app.dependency_overrides[get_current_active_user] = _get_current_active_user_override

  client = TestClient(app)
  # Remove dev key header, use empty headers or valid bearer if needed (but overridden)
  headers = {}
  payload = {"sections": [1], "agents": ["structurer"]}
  # Invoke the retry endpoint with section/agent targeting.
  response = client.post("/v1/jobs/job-retry-1/retry", json=payload, headers=headers)
  assert response.status_code == 200
  body = response.json()
  assert body["status"] == "queued"
  assert body["retry_count"] == 1
  assert body["retry_sections"] == [1]
  assert body["retry_agents"] == ["structurer"]
