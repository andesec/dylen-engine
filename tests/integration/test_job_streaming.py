from __future__ import annotations

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

# Ensure required settings are available before importing the app.
os.environ["DYLEN_ALLOWED_ORIGINS"] = "http://localhost"
os.environ["DYLEN_JOBS_AUTO_PROCESS"] = "0"

from app.core.security import get_current_active_user  # noqa: E402
from app.jobs.models import JobRecord  # noqa: E402
from app.main import app  # noqa: E402
from app.schema.sql import User, UserStatus  # noqa: E402


class InMemoryJobsRepo:
  """In-memory jobs repository for streaming status tests."""

  def __init__(self) -> None:
    self._jobs: dict[str, JobRecord] = {}

  async def create_job(self, record: JobRecord) -> None:
    self._jobs[record.job_id] = record

  async def get_job(self, job_id: str) -> JobRecord | None:
    return self._jobs.get(job_id)

  async def update_job(self, job_id: str, **kwargs: object) -> JobRecord | None:
    record = self._jobs.get(job_id)

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

  async def find_by_user_kind_idempotency_key(self, *, user_id: str | None, job_kind: str, idempotency_key: str) -> JobRecord | None:
    return None

  async def list_child_jobs(self, *, parent_job_id: str, include_done: bool = False) -> list[JobRecord]:
    children = [record for record in self._jobs.values() if record.parent_job_id == parent_job_id]
    if include_done:
      return children
    return [record for record in children if record.status != "done"]


@pytest.mark.anyio
async def test_job_status_streams_partial_results(monkeypatch: pytest.MonkeyPatch) -> None:
  repo = InMemoryJobsRepo()

  def _fake_repo(_settings: object) -> InMemoryJobsRepo:
    return repo

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
    return User(id="test-user-id", email="test@example.com", status=UserStatus.APPROVED)

  app.dependency_overrides[get_current_active_user] = _get_current_active_user_override

  from app.core.database import get_db

  async def _get_db_override():
    yield None

  app.dependency_overrides[get_db] = _get_db_override

  client = TestClient(app)
  headers = {}
  payload = {"job_kind": "lesson", "target_agent": "planner", "idempotency_key": "streaming-key", "payload": {"topic": "Streaming Test", "details": "test", "blueprint": "skillbuilding", "teaching_style": ["conceptual"], "depth": "highlights"}}
  create_resp = client.post("/v1/jobs", json=payload, headers=headers)
  assert create_resp.status_code == 200
  job_id = create_resp.json()["job_id"]
  assert create_resp.json()["expected_sections"] == 2

  # Simulate worker status updates and child fan-out over time.
  await repo.update_job(job_id, status="running")
  status_resp = client.get(f"/v1/jobs/{job_id}", headers=headers)
  assert status_resp.status_code == 200
  assert status_resp.json()["status"] == "running"

  await repo.create_job(
    JobRecord(
      job_id="child-1",
      user_id="test-user-id",
      job_kind="lesson",
      request={},
      status="queued",
      created_at="2024-01-01T00:00:00Z",
      updated_at="2024-01-01T00:00:00Z",
      parent_job_id=job_id,
      target_agent="section_builder",
      phase="queued",
      idempotency_key="child-1-key",
    )
  )
  status_resp = client.get(f"/v1/jobs/{job_id}", headers=headers)
  assert status_resp.status_code == 200
  assert len(status_resp.json()["child_jobs"]) == 1
