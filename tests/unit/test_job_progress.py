from __future__ import annotations

from dataclasses import replace

from app.jobs.models import JobRecord
from app.jobs.progress import JobProgressTracker, SectionProgress


class InMemoryJobsRepo:
    """Minimal in-memory jobs repo for progress tracker tests."""

    def __init__(self, record: JobRecord) -> None:
        self._record = record

    def create_job(self, record: JobRecord) -> None:
        self._record = record

    def get_job(self, job_id: str) -> JobRecord | None:

        if job_id != self._record.job_id:
            return None

        return self._record

    def update_job(self, job_id: str, **kwargs: object) -> JobRecord | None:

        if job_id != self._record.job_id:
            return None

        # Merge updates onto the latest record to mimic persistence behavior.
        self._record = replace(self._record, **{key: value for key, value in kwargs.items() if value is not None})
        return self._record

    def find_queued(self, limit: int = 5) -> list[JobRecord]:
        return []

    def find_by_idempotency_key(self, idempotency_key: str) -> JobRecord | None:
        return None


def test_job_progress_tracker_persists_partial_results() -> None:
    record = JobRecord(
        job_id="job-123",
        request={"topic": "Test"},
        status="queued",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
        phase="queued",
        logs=[],
    )
    repo = InMemoryJobsRepo(record)
    tracker = JobProgressTracker(job_id="job-123", jobs_repo=repo, total_steps=2, total_ai_calls=1, label_prefix="ai")
    # Update the tracker with a partial lesson payload and section metadata.
    section_progress = SectionProgress(index=0, title="Intro", status="generating", retry_count=0, completed_sections=0)
    tracker.complete_step(
        phase="collect",
        subphase="gather_section_1_of_2",
        message="Gathering section 1.",
        result_json={"title": "Partial", "blocks": []},
        expected_sections=2,
        section_progress=section_progress,
    )
    updated = repo.get_job("job-123")
    assert updated is not None
    assert updated.result_json == {"title": "Partial", "blocks": []}
    assert updated.expected_sections == 2
    assert updated.completed_sections == 0
    assert updated.completed_section_indexes == [0]
    assert updated.current_section_index == 0
    assert updated.current_section_status == "generating"
    assert updated.current_section_retry_count == 0
    assert updated.current_section_title == "Intro"
