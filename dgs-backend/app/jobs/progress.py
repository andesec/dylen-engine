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

    length: str | None
    sections: int
    required_calls: int
    max_calls: int

    @property
    def total_ai_calls(self) -> int:
        """Return the minimum AI calls needed for progress tracking."""

        return max(self.required_calls, 2)

    @property
    def label_prefix(self) -> str:
        """Prefix used for subphase labels."""

        return "section" if (self.length or "").lower() == "training" else "ai_call"

    def total_steps(self, *, include_validation: bool = True, include_repair: bool = False) -> int:
        """Compute the total number of progress steps."""

        calls = self.total_ai_calls + (1 if include_repair else 0)
        return calls + (1 if include_validation else 0)


def _coerce_sections(raw_sections: Any) -> int:
    """Validate and normalize the requested section count."""

    if raw_sections is None:
        return 1
    try:
        sections = int(raw_sections)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError("Section count must be an integer.") from exc
    if sections <= 0:
        raise ValueError("Section count must be positive.")
    if sections > 10:
        raise ValueError("Section count exceeds the maximum of 10.")
    return sections


def build_call_plan(request_data: Mapping[str, Any]) -> CallPlan:
    """Derive an AI call plan from the raw job request payload."""

    constraints = request_data.get("constraints") or {}
    length = constraints.get("length")
    sections = _coerce_sections(constraints.get("sections"))

    if length == "Highlights":
        required_calls, cap = 1, 2
    elif length == "Detailed":
        required_calls, cap = 2, 6
    elif length == "Training":
        required_calls = sections
        cap = min(24, sections)
    else:
        required_calls, cap = 2, 6

    if required_calls > cap:
        raise ValueError(
            f"Requested call volume ({required_calls}) exceeds the cap for {length or 'default'} "
            f"({cap})."
        )

    return CallPlan(length=length, sections=sections, required_calls=required_calls, max_calls=cap)


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

    def _update_job(
        self, *, status: JobStatus, phase: str, subphase: str | None = None
    ) -> JobRecord | None:
        record = self._jobs_repo.update_job(
            self._job_id,
            status=status,
            phase=phase,
            subphase=subphase,
            progress=self._progress_percent(),
            logs=self._logs,
        )
        if record and record.status == "canceled":
            raise JobCanceledError(f"Job {self._job_id} was canceled.")
        return record

    def set_cost(self, usage: list[dict[str, Any]], total: float) -> JobRecord | None:
        """Update the job's cost metrics."""
        return self._jobs_repo.update_job(
            self._job_id,
            cost={"total": total, "calls": usage},
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

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

    def complete_validation(
        self, *, message: str | None = None, status: JobStatus = "running"
    ) -> JobRecord | None:
        """Mark validation as finished and finalize progress."""

        if message:
            self.add_logs(message)
        self._completed_steps = self._total_steps
        return self._update_job(phase="validate", subphase="validation", status=status)

    def fail(self, *, phase: str, message: str) -> JobRecord | None:
        """Set the job to an error state."""

        self.add_logs(message)
        self._completed_steps = self._total_steps
        return self._jobs_repo.update_job(
            self._job_id,
            status="error",
            phase=phase,
            subphase="error",
            progress=self._progress_percent(),
            logs=self._logs,
        )

    @property
    def logs(self) -> list[str]:
        """Return a copy of the tracked logs."""

        return list(self._logs)
