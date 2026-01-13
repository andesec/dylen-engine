"""Background processor for queued lesson generation jobs."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from typing import Any

from pydantic import ValidationError

from app.ai.orchestrator import DgsOrchestrator, OrchestrationError, OrchestrationResult
from app.config import Settings
from app.jobs.models import JobRecord
from app.jobs.progress import (
    MAX_TRACKED_LOGS,
    JobCanceledError,
    JobProgressTracker,
    build_call_plan,
)
from app.main import (
    GenerateLessonRequest,
    WritingCheckRequest,
    _get_orchestrator,
    _resolve_learner_level,
    _resolve_model_selection,
    _resolve_primary_language,
)
from app.schema.serialize_lesson import lesson_to_shorthand
from app.schema.validate_lesson import validate_lesson
from app.storage.jobs_repo import JobsRepository
from app.writing.orchestrator import WritingCheckOrchestrator


class JobProcessor:
    """Coordinates execution of queued jobs."""

    def __init__(self, *, jobs_repo: JobsRepository, orchestrator: DgsOrchestrator, settings: Settings) -> None:
        self._jobs_repo = jobs_repo
        self._orchestrator = orchestrator
        self._settings = settings

    async def process_job(self, job: JobRecord) -> JobRecord | None:
        """Execute a single queued job, routing by type."""
        if job.status != "queued":
            return job

        if "text" in job.request and "criteria" in job.request:
            return await self._process_writing_check(job)
        return await self._process_lesson_generation(job)

    async def _process_lesson_generation(self, job: JobRecord) -> JobRecord | None:
        """Execute a single queued lesson generation job."""

        base_logs = job.logs + ["Job acknowledged by worker."]
        try:
            call_plan = build_call_plan(job.request, merge_gatherer_structurer=self._settings.merge_gatherer_structurer)
        except ValueError as exc:
            error_log = f"Validation failed: {exc}"
            payload = {"status": "error", "phase": "failed", "subphase": "validation", "progress": 100.0, "logs": base_logs + [error_log]}
            self._jobs_repo.update_job(job.job_id, **payload)
            return None

        total_steps = call_plan.total_steps(include_validation=True, include_repair=True)
        merge_label = "enabled" if self._settings.merge_gatherer_structurer else "disabled"
        initial_logs = base_logs + [
            f"Planned AI calls: {call_plan.required_calls}/{call_plan.max_calls}",
            f"Depth: {call_plan.depth}",
            f"Planner calls: {call_plan.planner_calls}",
            f"Gatherer calls: {call_plan.gather_calls}",
            f"Structurer calls: {call_plan.structurer_calls}",
            f"Repair calls: {call_plan.repair_calls}",
            f"Merged gatherer+structurer: {merge_label}",
        ]
        tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=total_steps, total_ai_calls=call_plan.total_ai_calls, label_prefix=call_plan.label_prefix, initial_logs=initial_logs)
        tracker.set_phase(phase="plan", subphase="planner_start")

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

            orchestration_result = await self._run_orchestration(job.job_id, job.request, tracker=tracker, timeout_checker=_check_timeouts)

            if _check_timeouts():
                return None

            # Surface orchestration logs even when validation fails.
            tracker.extend_logs(orchestration_result.logs)
            lesson_model_validation = validate_lesson(orchestration_result.lesson_json)
            ok, errors, lesson_model = lesson_model_validation
            validation = {"ok": ok, "errors": errors}
            if not ok or lesson_model is None:
                raise ValueError(f"Validation failed with {len(errors)} error(s).")

            shorthand = lesson_to_shorthand(lesson_model)
            tracker.complete_validation(message="Validate phase complete.", status="done")
            cost_summary = _summarize_cost(orchestration_result.usage, orchestration_result.total_cost)
            tracker.set_cost(cost_summary)
            log_updates = tracker.logs[-MAX_TRACKED_LOGS:]
            log_updates.append("Job completed successfully.")
            completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            payload = {
                "status": "done",
                "phase": "validate",
                "subphase": "complete",
                "progress": 100.0,
                "logs": log_updates,
                "result_json": shorthand,
                "artifacts": orchestration_result.artifacts,
                "validation": validation,
                "cost": cost_summary,
                "completed_at": completed_at,
            }
            updated = self._jobs_repo.update_job(job.job_id, **payload)
            return updated
        except JobCanceledError:
            # Re-fetch the record to ensure we have the final canceled state
            return self._jobs_repo.get_job(job.job_id)

        except OrchestrationError as exc:
            # Preserve pipeline logs when orchestration fails fast.
            tracker.extend_logs(exc.logs)
            error_log = f"Job failed: {exc}"
            tracker.fail(phase="failed", message=error_log)
            payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs}
            self._jobs_repo.update_job(job.job_id, **payload)
            return None

        except Exception as exc:  # noqa: BLE001
            error_log = f"Job failed: {exc}"
            tracker.fail(phase="failed", message=error_log)
            payload = {"status": "error", "phase": "failed", "progress": 100.0, "logs": tracker.logs}
            self._jobs_repo.update_job(job.job_id, **payload)
            return None

    async def _process_writing_check(self, job: JobRecord) -> JobRecord | None:
        """Execute a background writing task evaluation."""
        tracker = JobProgressTracker(job_id=job.job_id, jobs_repo=self._jobs_repo, total_steps=1, total_ai_calls=1, label_prefix="check", initial_logs=["Writing check acknowledged."])
        tracker.set_phase(phase="evaluating", subphase="ai_check")

        try:
            # Validate and hydrate the request so optional model overrides are honored.
            request_model = WritingCheckRequest.model_validate(job.request)
            checker_model = request_model.checker_model or self._settings.structurer_model
            orchestrator = WritingCheckOrchestrator(provider=self._settings.structurer_provider, model=checker_model)
            result = await orchestrator.check_response(text=request_model.text, criteria=request_model.criteria)

            tracker.extend_logs(result.logs)
            cost_summary = _summarize_cost(result.usage, result.total_cost)
            tracker.set_cost(cost_summary)
            completed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            result_json = {"ok": result.ok, "issues": result.issues, "feedback": result.feedback}
            payload = {"status": "done", "phase": "complete", "progress": 100.0, "logs": tracker.logs, "result_json": result_json, "cost": cost_summary, "completed_at": completed_at}
            updated = self._jobs_repo.update_job(job.job_id, **payload)
            return updated

        except JobCanceledError:
            return self._jobs_repo.get_job(job.job_id)

        except Exception as exc:
            tracker.fail(phase="failed", message=f"Writing check failed: {exc}")
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

    async def _run_orchestration(self, job_id: str, request: dict[str, Any], *, tracker: JobProgressTracker | None = None, timeout_checker: Callable[[], bool] | None = None) -> OrchestrationResult:
        """Execute the orchestration pipeline with guarded parameters."""

        try:

            # Drop deprecated fields so legacy records can still be parsed.
            if "mode" in request:
                request = {key: value for key, value in request.items() if key != "mode"}

            request_model = GenerateLessonRequest.model_validate(request)

        except ValidationError as exc:
            raise ValueError("Stored job request is invalid.") from exc
        topic = request_model.topic

        if len(topic) > self._settings.max_topic_length:
            raise ValueError(f"Topic exceeds max length of {self._settings.max_topic_length}.")

        # Resolve per-agent model overrides so queued jobs honor request settings.
        selection = _resolve_model_selection(self._settings, models=request_model.models)
        (
            gatherer_provider,
            gatherer_model,
            planner_provider,
            planner_model,
            structurer_provider,
            structurer_model,
            repairer_provider,
            repairer_model,
        ) = selection
        language = _resolve_primary_language(request_model)
        learner_level = _resolve_learner_level(request_model)
        schema_version = request_model.schema_version or self._settings.schema_version

        orchestrator = _get_orchestrator(
            self._settings,
            gatherer_provider=gatherer_provider,
            gatherer_model=gatherer_model,
            planner_provider=planner_provider,
            planner_model=planner_model,
            structurer_provider=structurer_provider,
            structurer_model=structurer_model,
            repair_provider=repairer_provider,
            repair_model=repairer_model,
        )

        logs: list[str] = [
            f"Starting job {job_id}",
            f"Topic: {topic[:80]}{'...' if len(topic) > 80 else ''}",
            f"Gatherer provider: {gatherer_provider}",
            f"Gatherer model: {gatherer_model or 'default'}",
            f"Planner provider: {planner_provider}",
            f"Planner model: {planner_model or 'default'}",
            f"Structurer provider: {structurer_provider}",
            f"Structurer model: {structurer_model or 'default'}",
            f"Repairer provider: {repairer_provider}",
            f"Repairer model: {repairer_model or 'default'}",
        ]

        Msgs = list[str] | None
        def _progress_callback(phase: str, subphase: str | None, messages: Msgs = None, advance: bool = True) -> None:
            if tracker is None:
                return

            # Active guardrail check
            if timeout_checker and timeout_checker():
                # Note: We can't easily raise an exception here that Orchestrator will catch nicely,
                # but Orchestrator has its own try/except now.
                # If we raise here, Orchestrator will catch it and return partial usage.
                raise TimeoutError("Job hit timeout during orchestration.")

            # Check for cancellation
            record = self._jobs_repo.get_job(job_id)
            if record and record.status == "canceled":
                raise JobCanceledError(f"Job {job_id} was canceled during orchestration.")

            log_message = "; ".join(messages or [])
            if advance:
                tracker.complete_step(phase=phase, subphase=subphase, message=log_message or None)
            else:
                if log_message:
                    tracker.add_logs(log_message)
                tracker.set_phase(phase=phase, subphase=subphase)

        result = await orchestrator.generate_lesson(
            topic=topic,
            details=request_model.details,
            blueprint=request_model.blueprint,
            teaching_style=request_model.teaching_style,
            learner_level=learner_level,
            depth=request_model.depth,
            widgets=request_model.widgets,
            schema_version=schema_version,
            structurer_model=structurer_model,
            gatherer_model=gatherer_model,
            structured_output=True,
            language=language,
            progress_callback=_progress_callback,
        )

        merged_logs = list(_merge_logs(logs, result.logs))
        if tracker is not None:
            tracker.set_phase(phase="validate", subphase="validation")
        return result.__class__(lesson_json=result.lesson_json, provider_a=result.provider_a, model_a=result.model_a, provider_b=result.provider_b, model_b=result.model_b, logs=merged_logs)


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


def _summarize_cost(usage: list[dict[str, Any]], total_cost: float) -> dict[str, Any]:
    # Roll up token counts and total cost into the job payload expected by DLE.
    total_input_tokens = 0
    total_output_tokens = 0
    for entry in usage:
        total_input_tokens += int(entry.get("input_tokens") or entry.get("prompt_tokens") or 0)
        output_tokens = int(entry.get("output_tokens") or entry.get("completion_tokens") or 0)
        total_output_tokens += output_tokens
    return {
        "currency": "USD",
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cost": total_cost,
        "calls": usage,
    }
