"""Background processor for queued lesson generation jobs."""

from __future__ import annotations

import os
import time
from collections.abc import Iterable
from typing import Any

from app.ai.orchestrator import DgsOrchestrator, OrchestrationResult
from app.config import Settings
from app.jobs.models import JobRecord
from app.jobs.progress import MAX_TRACKED_LOGS, JobProgressTracker, build_call_plan
from app.main import _resolve_structurer_model
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
        try:
            call_plan = build_call_plan(job.request)
        except ValueError as exc:
            error_log = f"Validation failed: {exc}"
            self._jobs_repo.update_job(
                job.job_id,
                status="error",
                phase="failed",
                subphase="validation",
                progress=100.0,
                logs=base_logs + [error_log],
            )
            return None

        tracker = JobProgressTracker(
            job_id=job.job_id,
            jobs_repo=self._jobs_repo,
            total_steps=call_plan.total_steps(include_validation=True),
            total_ai_calls=call_plan.total_ai_calls,
            label_prefix=call_plan.label_prefix,
            initial_logs=base_logs
            + [
                f"Planned AI calls: {call_plan.required_calls}/{call_plan.max_calls}",
                f"Sections: {call_plan.sections}",
            ],
        )
        tracker.set_phase(phase="collect", subphase=tracker.current_ai_subphase())

        start_time = time.monotonic()
        soft_timeout = _parse_timeout_env("JOB_SOFT_TIMEOUT_SECONDS")
        hard_timeout = _parse_timeout_env("JOB_HARD_TIMEOUT_SECONDS")
        soft_timeout_recorded = False

        def _check_timeouts() -> bool:
            nonlocal soft_timeout_recorded
            elapsed = time.monotonic() - start_time
            if hard_timeout and elapsed >= hard_timeout:
                tracker.fail(phase="failed", message="Job hit hard timeout.")
                return True
            if soft_timeout and elapsed >= soft_timeout and not soft_timeout_recorded:
                tracker.add_logs("Soft timeout threshold exceeded; continuing until hard timeout.")
                soft_timeout_recorded = True
            return False

        tracker.add_logs("Collect phase started.")
        try:
            if _check_timeouts():
                return None

            orchestration_result = await self._run_orchestration(
                job.job_id,
                job.request,
                tracker=tracker,
            )

            if _check_timeouts():
                return None

            lesson_model_validation = validate_lesson(orchestration_result.lesson_json)
            ok, errors, lesson_model = lesson_model_validation
            validation = {"ok": ok, "errors": errors}
            if not ok or lesson_model is None:
                raise ValueError(f"Validation failed with {len(errors)} error(s).")

            shorthand = lesson_to_shorthand(lesson_model)
            tracker.extend_logs(orchestration_result.logs)
            tracker.complete_validation(message="Validate phase complete.", status="done")
            log_updates = tracker.logs[-MAX_TRACKED_LOGS:]
            log_updates.append("Job completed successfully.")
            updated = self._jobs_repo.update_job(
                job.job_id,
                status="done",
                phase="validate",
                subphase="complete",
                progress=100.0,
                logs=log_updates,
                result_json=shorthand,
                validation=validation,
                completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            return updated
        except Exception as exc:  # noqa: BLE001
            error_log = f"Job failed: {exc}"
            tracker.fail(phase="failed", message=error_log)
            self._jobs_repo.update_job(
                job.job_id,
                status="error",
                phase="failed",
                progress=100.0,
                logs=tracker.logs,
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

    async def _run_orchestration(
        self,
        job_id: str,
        request: dict[str, Any],
        *,
        tracker: JobProgressTracker | None = None,
    ) -> OrchestrationResult:
        """Execute the orchestration pipeline with guarded parameters."""
        topic: str = request["topic"]
        topic_details: str | None = request.get("topic_details")
        constraints = request.get("constraints")
        schema_version = request.get("schema_version") or self._settings.schema_version
        mode = request.get("mode")

        if len(topic) > self._settings.max_topic_length:
            raise ValueError(f"Topic exceeds max length of {self._settings.max_topic_length}.")

        structurer_model = _resolve_structurer_model(self._settings, mode)

        logs: list[str] = [
            f"Starting job {job_id}",
            f"Topic: {topic[:80]}{'...' if len(topic) > 80 else ''}",
            f"Structurer model: {structurer_model or 'default'}",
        ]

        def _progress_callback(phase: str, messages: list[str] | None = None) -> None:
            if tracker is None:
                return
            tracker.complete_ai_call(phase=phase, message="; ".join(messages or []))
            tracker.set_phase(phase="transform", subphase=tracker.current_ai_subphase())

        result = await self._orchestrator.generate_lesson(
            topic=topic,
            topic_details=topic_details,
            constraints=constraints,
            schema_version=schema_version,
            structurer_model=structurer_model,
            progress_callback=_progress_callback,
        )

        merged_logs = list(_merge_logs(logs, result.logs))
        if tracker is not None:
            tracker.set_phase(phase="validate", subphase="validation")
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


def _parse_timeout_env(var_name: str) -> int:
    """Parse a timeout value from the environment."""

    raw_value = os.getenv(var_name)
    if not raw_value:
        return 0
    try:
        seconds = int(raw_value)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"{var_name} must be an integer.") from exc
    return max(0, seconds)
