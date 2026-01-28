from __future__ import annotations

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

# Ensure required settings are available before importing the app.
os.environ["DGS_ALLOWED_ORIGINS"] = "http://localhost"
os.environ["DGS_JOBS_AUTO_PROCESS"] = "0"

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
  payload = {"topic": "Streaming Test", "depth": "highlights"}
  create_resp = client.post("/v1/jobs", json=payload, headers=headers)
  assert create_resp.status_code == 200
  job_id = create_resp.json()["job_id"]
  assert create_resp.json()["expected_sections"] == 2

  # Simulate the worker streaming partial results over time.
  await repo.update_job(job_id, status="running", result_json={"title": "Streaming Test", "blocks": []}, completed_sections=0, expected_sections=2, current_section_index=0, current_section_status="generating")
  status_resp = client.get(f"/v1/jobs/{job_id}", headers=headers)
  assert status_resp.status_code == 200
  assert status_resp.json()["result"]["blocks"] == []

  await repo.update_job(job_id, status="running", result_json={"title": "Streaming Test", "blocks": [{"section": "Intro", "items": []}]}, completed_sections=1, expected_sections=2, current_section_index=1, current_section_status="generating")
  status_resp = client.get(f"/v1/jobs/{job_id}", headers=headers)
  assert status_resp.status_code == 200
  assert len(status_resp.json()["result"]["blocks"]) == 1
