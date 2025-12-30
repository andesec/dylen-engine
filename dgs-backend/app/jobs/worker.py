"""Background processor for queued lesson generation jobs."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.ai.orchestrator import DgsOrchestrator, OrchestrationResult
from app.config import Settings
from app.jobs.models import JobRecord
from app.main import (
    GenerateLessonRequest,
    _build_constraints,
    _get_orchestrator,
    _resolve_structurer_selection,
)
from app.schema.serialize_lesson import lesson_to_shorthand
from app.schema.validate_lesson import validate_lesson
from app.storage.jobs_repo import JobsRepository


class JobProcessor:
    """Coordinates execution of queued jobs."""

    def __init__(
        self, *, jobs_repo: JobsRepository, orchestrator: DgsOrchestrator, settings: Settings
    ) -> None:
        self._jobs_repo = jobs_repo
        self._orchestrator = orchestrator
        self._settings = settings

    async def process_job(self, job: JobRecord) -> JobRecord | None:
        """Execute a single queued job."""
        if job.status != "queued":
            return job

        base_logs = job.logs + ["Job acknowledged by worker."]
        self._jobs_repo.update_job(
            job.job_id,
            status="running",
            phase="initializing",
            progress=0.05,
            logs=base_logs,
        )
        self._jobs_repo.update_job(
            job.job_id,
            status="running",
            phase="orchestrating",
            subphase="pipeline",
            progress=0.2,
            logs=base_logs + ["Starting orchestration pipeline."],
        )

        try:
            orchestration_result = await self._run_orchestration(job.job_id, job.request)
            lesson_model_validation = validate_lesson(orchestration_result.lesson_json)
            ok, errors, lesson_model = lesson_model_validation
            validation = {"ok": ok, "errors": errors}
            if not ok or lesson_model is None:
                raise ValueError(f"Validation failed with {len(errors)} error(s).")

            shorthand = lesson_to_shorthand(lesson_model)
            log_updates = base_logs + orchestration_result.logs + ["Job completed successfully."]
            updated = self._jobs_repo.update_job(
                job.job_id,
                status="done",
                phase="complete",
                progress=1.0,
                logs=log_updates,
                result_json=shorthand,
                validation=validation,
                completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            return updated
        except Exception as exc:  # noqa: BLE001
            error_log = f"Job failed: {exc}"
            log_updates = base_logs + [error_log]
            self._jobs_repo.update_job(
                job.job_id,
                status="error",
                phase="failed",
                progress=1.0,
                logs=log_updates,
            )
            return None

    async def process_queue(self, limit: int = 5) -> list[JobRecord]:
        """Process a small batch of queued jobs."""
        queued = self._jobs_repo.find_queued(limit=limit)
        results: list[JobRecord] = []
        for job in queued:
            processed = await self.process_job(job)
            if processed:
                results.append(processed)
        return results

    async def _run_orchestration(self, job_id: str, request: dict[str, Any]) -> OrchestrationResult:
        """Execute the orchestration pipeline with guarded parameters."""
        try:
            request_model = GenerateLessonRequest.model_validate(request)
        except ValidationError as exc:
            raise ValueError("Stored job request is invalid.") from exc
        topic = request_model.topic
        if len(topic) > self._settings.max_topic_length:
            raise ValueError(f"Topic exceeds max length of {self._settings.max_topic_length}.")

        structurer_provider, structurer_model = _resolve_structurer_selection(
            self._settings, request_model.config
        )
        constraints = _build_constraints(request_model.config)
        schema_version = request_model.schema_version or self._settings.schema_version

        orchestrator = _get_orchestrator(
            self._settings,
            structurer_provider=structurer_provider,
            structurer_model=structurer_model,
        )

        logs: list[str] = [
            f"Starting job {job_id}",
            f"Topic: {topic[:80]}{'...' if len(topic) > 80 else ''}",
            f"Structurer provider: {structurer_provider}",
            f"Structurer model: {structurer_model or 'default'}",
        ]

        result = await orchestrator.generate_lesson(
            topic=topic,
            prompt=request_model.prompt,
            constraints=constraints,
            schema_version=schema_version,
            structurer_model=structurer_model,
            structured_output=request_model.config.structured_output,
            language=request_model.config.language,
        )

        merged_logs = list(_merge_logs(logs, result.logs))
        return result.__class__(
            lesson_json=result.lesson_json,
            provider_a=result.provider_a,
            model_a=result.model_a,
            provider_b=result.provider_b,
            model_b=result.model_b,
            logs=merged_logs,
        )


def _merge_logs(*log_sets: Iterable[str]) -> Iterable[str]:
    for logs in log_sets:
        yield from logs
