from __future__ import annotations

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

# Ensure required settings are available before importing the app.
os.environ.setdefault("DGS_DEV_KEY", "test-key")
os.environ.setdefault("DGS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("DGS_JOBS_AUTO_PROCESS", "0")

from app.jobs.models import JobRecord
from app.main import app


class InMemoryJobsRepo:
  """In-memory jobs repository for streaming status tests."""

  def __init__(self) -> None:
    self._jobs: dict[str, JobRecord] = {}

  def create_job(self, record: JobRecord) -> None:
    self._jobs[record.job_id] = record

  def get_job(self, job_id: str) -> JobRecord | None:
    return self._jobs.get(job_id)

  def update_job(self, job_id: str, **kwargs: object) -> JobRecord | None:
    record = self._jobs.get(job_id)

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


def test_job_status_streams_partial_results(monkeypatch: pytest.MonkeyPatch) -> None:
  repo = InMemoryJobsRepo()

  def _fake_repo(_settings: object) -> InMemoryJobsRepo:
    return repo

  monkeypatch.setattr("app.main._get_jobs_repo", _fake_repo)
  client = TestClient(app)
  headers = {"X-DGS-Dev-Key": "test-key"}
  payload = {"topic": "Streaming Test", "depth": "highlights"}
  create_resp = client.post("/v1/jobs", json=payload, headers=headers)
  assert create_resp.status_code == 200
  job_id = create_resp.json()["job_id"]
  assert create_resp.json()["expected_sections"] == 2

  # Simulate the worker streaming partial results over time.
  repo.update_job(
    job_id, status="running", result_json={"title": "Streaming Test", "blocks": []}, completed_sections=0, expected_sections=2, current_section_index=0, current_section_status="generating"
  )
  status_resp = client.get(f"/v1/jobs/{job_id}", headers=headers)
  assert status_resp.status_code == 200
  assert status_resp.json()["result"]["blocks"] == []

  repo.update_job(
    job_id,
    status="running",
    result_json={"title": "Streaming Test", "blocks": [{"section": "Intro", "items": []}]},
    completed_sections=1,
    expected_sections=2,
    current_section_index=1,
    current_section_status="generating",
  )
  status_resp = client.get(f"/v1/jobs/{job_id}", headers=headers)
  assert status_resp.status_code == 200
  assert len(status_resp.json()["result"]["blocks"]) == 1
