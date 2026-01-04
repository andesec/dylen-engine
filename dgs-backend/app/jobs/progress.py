"""Job progress planning and tracking utilities."""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.jobs.models import JobRecord, JobStatus
from app.storage.jobs_repo import JobsRepository

MAX_TRACKED_LOGS = 100


class JobCanceledError(Exception):
    """Exception raised when a job is canceled by the user."""


@dataclass(frozen=True)
class CallPlan:
    """Represents the expected AI call volume for a job."""

    depth: int
    planner_calls: int
    gather_calls: int
    structurer_calls: int
    repair_calls: int
    stitch_calls: int
    required_calls: int
    max_calls: int

    @property
    def total_ai_calls(self) -> int:
        """Return the minimum AI calls needed for progress tracking."""

        return max(self.required_calls, 2)

    @property
    def label_prefix(self) -> str:
        """Prefix used for subphase labels."""

        return "ai_call"

    def total_steps(self, *, include_validation: bool = True, include_repair: bool = True) -> int:
        """Compute the total number of progress steps."""

        planner_steps = 2
        gather_steps = self.gather_calls * 2
        structurer_steps = self.structurer_calls * 2
        stitch_steps = self.stitch_calls
        steps = planner_steps + gather_steps + structurer_steps + stitch_steps
        if include_validation:
            steps += 1
        return max(steps, 1)


def _coerce_depth(raw_depth: Any) -> int:
    """Validate and normalize the requested depth."""

    # Accept DLE depth labels in addition to numeric values for backward compatibility.
    if raw_depth is None:
        return 2
    if isinstance(raw_depth, str):
        normalized = raw_depth.strip().lower()
        if normalized == "highlights":
            return 2
        if normalized == "detailed":
            return 6
        if normalized == "training":
            return 10
        if normalized.isdigit():
            raw_depth = int(normalized)
    try:
        depth = int(raw_depth)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError("Depth must be Highlights, Detailed, Training, or an integer between 2 and 10.") from exc
    if depth < 2:
        raise ValueError("Depth must be at least 2.")
    if depth > 10:
        raise ValueError("Depth exceeds the maximum of 10.")
    return depth


def build_call_plan(request_data: Mapping[str, Any]) -> CallPlan:
    """Derive an AI call plan from the raw job request payload."""

    depth = _coerce_depth(request_data.get("depth"))

    planner_calls = 1
    gather_calls = depth
    structurer_calls = depth
    repair_calls = depth
    stitch_calls = 1
    total_calls = planner_calls + gather_calls + structurer_calls + repair_calls

    max_gather_calls = 10
    max_structurer_calls = 10
    max_repair_calls = 10
    max_total_calls = 35

    if gather_calls > max_gather_calls:
        raise ValueError("Lower depth to reduce gatherer calls.")
    if structurer_calls > max_structurer_calls:
        raise ValueError("Lower depth to reduce structurer calls.")
    if repair_calls > max_repair_calls:
        raise ValueError("Lower depth to reduce repair calls.")
    if total_calls > max_total_calls:
        raise ValueError("Lower depth to reduce total calls.")

    plan = CallPlan(depth=depth, planner_calls=planner_calls, gather_calls=gather_calls, structurer_calls=structurer_calls, repair_calls=repair_calls, stitch_calls=stitch_calls, required_calls=total_calls, max_calls=max_total_calls)
    return plan


class JobProgressTracker:
    """Track job progress, phases, and log updates."""

    def __init__(
        self,
        *,
        job_id: str,
        jobs_repo: JobsRepository,
        total_steps: int,
        total_ai_calls: int,
        label_prefix: str,
        initial_logs: Iterable[str] | None = None,
    ) -> None:
        self._job_id = job_id
        self._jobs_repo = jobs_repo
        self._total_steps = max(total_steps, 1)
        self._total_ai_calls = max(total_ai_calls, 1)
        self._label_prefix = label_prefix
        self._completed_steps = 0
        self._ai_call_index = 1
        self._logs: list[str] = list(initial_logs or [])[-MAX_TRACKED_LOGS:]

    def add_logs(self, *messages: str) -> None:
        """Append log lines while preserving the rolling window."""

        self._logs.extend(messages)
        if len(self._logs) > MAX_TRACKED_LOGS:
            self._logs = self._logs[-MAX_TRACKED_LOGS:]

    def extend_logs(self, messages: Iterable[str]) -> None:
        """Append many log lines efficiently."""

        for message in messages:
            self.add_logs(message)

    def current_ai_subphase(self) -> str:
        """Return the subphase label for the active AI call."""

        return f"{self._label_prefix}_{self._ai_call_index}_of_{self._total_ai_calls}"

    def _progress_percent(self) -> float:
        if self._total_steps == 0:
            return 0.0
        return min(round((self._completed_steps / self._total_steps) * 100, 2), 100.0)

    def _update_job(self, *, status: JobStatus, phase: str, subphase: str | None = None) -> JobRecord | None:
        payload = {
            "status": status,
            "phase": phase,
            "subphase": subphase,
            "progress": self._progress_percent(),
            "total_steps": self._total_steps,
            "completed_steps": self._completed_steps,
            "logs": self._logs,
        }
        record = self._jobs_repo.update_job(self._job_id, **payload)
        if record and record.status == "canceled":
            raise JobCanceledError(f"Job {self._job_id} was canceled.")
        return record

    def set_cost(self, cost: dict[str, Any]) -> JobRecord | None:
        """Update the job's cost metrics."""
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        payload = {"cost": cost, "updated_at": timestamp}
        return self._jobs_repo.update_job(self._job_id, **payload)

    def set_phase(self, *, phase: str, subphase: str | None = None) -> JobRecord | None:
        """Update the phase without advancing progress."""

        return self._update_job(status="running", phase=phase, subphase=subphase)

    def complete_ai_call(self, *, phase: str, message: str | None = None) -> JobRecord | None:
        """Mark an AI call as finished and advance progress."""

        if message:
            self.add_logs(message)
        subphase = self.current_ai_subphase()
        self._completed_steps = min(self._completed_steps + 1, self._total_steps)
        record = self._update_job(status="running", phase=phase, subphase=subphase)
        self._ai_call_index = min(self._ai_call_index + 1, self._total_ai_calls)
        return record

    def complete_step(self, *, phase: str, subphase: str | None, message: str | None = None) -> JobRecord | None:
        """Advance progress with a custom subphase label."""

        if message:
            self.add_logs(message)
        self._completed_steps = min(self._completed_steps + 1, self._total_steps)
        return self._update_job(status="running", phase=phase, subphase=subphase)

    def complete_validation(self, *, message: str | None = None, status: JobStatus = "running") -> JobRecord | None:
        """Mark validation as finished and finalize progress."""

        if message:
            self.add_logs(message)
        self._completed_steps = self._total_steps
        return self._update_job(phase="validate", subphase="validation", status=status)

    def fail(self, *, phase: str, message: str) -> JobRecord | None:
        """Set the job to an error state."""

        self.add_logs(message)
        self._completed_steps = self._total_steps
        payload = {"status": "error", "phase": phase, "subphase": "error", "progress": self._progress_percent(), "logs": self._logs}
        return self._jobs_repo.update_job(self._job_id, **payload)

    @property
    def logs(self) -> list[str]:
        """Return a copy of the tracked logs."""

        return list(self._logs)
