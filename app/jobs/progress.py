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

  section_count: int
  planner_calls: int
  section_builder_calls: int
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
    section_builder_steps = self.section_builder_calls * 2
    stitch_steps = self.stitch_calls
    steps = planner_steps + section_builder_steps + stitch_steps
    if include_validation:
      steps += 1
    return max(steps, 1)


def _coerce_depth(raw_depth: Any) -> int:
  """Validate and normalize the requested section count."""

  # Accept legacy Dylen depth labels in addition to numeric values for backward compatibility.
  if raw_depth is None:
    return 2
  if isinstance(raw_depth, str):
    normalized = raw_depth.strip().lower()
    # Map legacy depth labels to section counts
    if normalized == "highlights":
      return 2
    if normalized == "detailed":
      return 4
    if normalized == "training":
      return 5
    if normalized.isdigit():
      raw_depth = int(normalized)
  try:
    section_count = int(raw_depth)
  except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
    raise ValueError("Section count must be between 1 and 5, or Highlights/Detailed/In-Depth.") from exc
  if section_count < 1:
    raise ValueError("Section count must be at least 1.")
  if section_count > 5:
    raise ValueError("Section count exceeds the maximum of 5.")
  return section_count


def build_call_plan(request_data: Mapping[str, Any]) -> CallPlan:
  """Derive an AI call plan from the raw job request payload."""

  # Normalize section_count input before computing call counts.
  section_count = _coerce_depth(request_data.get("section_count") or request_data.get("depth"))

  # Set per-phase call counts based on section count.
  planner_calls = 1
  section_builder_calls = section_count
  repair_calls = section_count
  stitch_calls = 1

  # Aggregate total calls for overall guardrails.
  total_calls = planner_calls + section_builder_calls + repair_calls

  # Guardrails keep the plan within expected operational limits.
  max_section_builder_calls = 5
  max_repair_calls = 5
  max_total_calls = 15

  if section_builder_calls > max_section_builder_calls:
    raise ValueError("Lower section count to reduce section builder calls.")

  if repair_calls > max_repair_calls:
    raise ValueError("Lower section count to reduce repair calls.")

  if total_calls > max_total_calls:
    raise ValueError("Lower section count to reduce total calls.")

  plan = CallPlan(section_count=section_count, planner_calls=planner_calls, section_builder_calls=section_builder_calls, repair_calls=repair_calls, stitch_calls=stitch_calls, required_calls=total_calls, max_calls=max_total_calls)
  return plan


@dataclass(frozen=True)
class SectionProgress:
  """Track section-level status for streaming updates."""

  index: int
  title: str | None
  status: str
  retry_count: int | None = None
  completed_sections: int | None = None


class JobProgressTracker:
  """Track job progress, phases, and log updates."""

  def __init__(self, *, job_id: str, jobs_repo: JobsRepository, total_steps: int, total_ai_calls: int, label_prefix: str, initial_logs: Iterable[str] | None = None, completed_section_indexes: Iterable[int] | None = None) -> None:
    self._job_id = job_id
    self._jobs_repo = jobs_repo
    self._total_steps = max(total_steps, 1)
    self._total_ai_calls = max(total_ai_calls, 1)
    self._label_prefix = label_prefix
    self._completed_steps = 0
    self._ai_call_index = 1
    self._logs: list[str] = list(initial_logs or [])[-MAX_TRACKED_LOGS:]
    # Preserve existing completed sections so retries can merge partial output.
    self._completed_section_indexes = list(completed_section_indexes or [])

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

  async def _update_job(self, *, status: JobStatus, phase: str, subphase: str | None = None, result_json: dict[str, Any] | None = None, expected_sections: int | None = None, section_progress: SectionProgress | None = None) -> JobRecord | None:
    # Build the base payload for persistence.
    payload = {"status": status, "phase": phase, "subphase": subphase, "progress": self._progress_percent(), "total_steps": self._total_steps, "completed_steps": self._completed_steps, "logs": self._logs}

    # Attach partial lesson JSON when streaming progress updates.
    if result_json is not None:
      payload["result_json"] = result_json

    # Attach section counters when available for UI progress.
    if expected_sections is not None:
      payload["expected_sections"] = expected_sections

    # Attach the active section metadata when available.
    if section_progress is not None:
      # Record completed section indices for retry merging.
      if section_progress.status == "completed":
        self._record_completed_section(section_progress.index)

      payload["completed_sections"] = section_progress.completed_sections
      payload["current_section_index"] = section_progress.index
      payload["current_section_status"] = section_progress.status
      payload["current_section_retry_count"] = section_progress.retry_count
      payload["current_section_title"] = section_progress.title
      payload["completed_section_indexes"] = list(self._completed_section_indexes)

    record = await self._jobs_repo.update_job(self._job_id, **payload)

    if record and record.status == "canceled":
      raise JobCanceledError(f"Job {self._job_id} was canceled.")

    return record

  def _record_completed_section(self, index: int) -> None:
    """Track completed sections in completion order while avoiding duplicates."""
    # Avoid duplicates so section-to-block alignment stays deterministic.
    if index in self._completed_section_indexes:
      return

    self._completed_section_indexes.append(index)

  async def set_cost(self, cost: dict[str, Any]) -> JobRecord | None:
    """Update the job's cost metrics."""
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = {"cost": cost, "updated_at": timestamp}
    return await self._jobs_repo.update_job(self._job_id, **payload)

  async def set_phase(self, *, phase: str, subphase: str | None = None, result_json: dict[str, Any] | None = None, expected_sections: int | None = None, section_progress: SectionProgress | None = None) -> JobRecord | None:
    """Update the phase without advancing progress."""

    return await self._update_job(status="running", phase=phase, subphase=subphase, result_json=result_json, expected_sections=expected_sections, section_progress=section_progress)

  async def complete_ai_call(self, *, phase: str, message: str | None = None, result_json: dict[str, Any] | None = None, expected_sections: int | None = None, section_progress: SectionProgress | None = None) -> JobRecord | None:
    """Mark an AI call as finished and advance progress."""

    if message:
      self.add_logs(message)
    subphase = self.current_ai_subphase()
    self._completed_steps = min(self._completed_steps + 1, self._total_steps)
    record = await self._update_job(status="running", phase=phase, subphase=subphase, result_json=result_json, expected_sections=expected_sections, section_progress=section_progress)
    self._ai_call_index = min(self._ai_call_index + 1, self._total_ai_calls)
    return record

  async def complete_step(self, *, phase: str, subphase: str | None, message: str | None = None, result_json: dict[str, Any] | None = None, expected_sections: int | None = None, section_progress: SectionProgress | None = None) -> JobRecord | None:
    """Advance progress with a custom subphase label."""

    if message:
      self.add_logs(message)
    self._completed_steps = min(self._completed_steps + 1, self._total_steps)
    return await self._update_job(status="running", phase=phase, subphase=subphase, result_json=result_json, expected_sections=expected_sections, section_progress=section_progress)

  async def complete_validation(self, *, message: str | None = None, status: JobStatus = "running", result_json: dict[str, Any] | None = None, expected_sections: int | None = None, section_progress: SectionProgress | None = None) -> JobRecord | None:
    """Mark validation as finished and finalize progress."""

    if message:
      self.add_logs(message)
    self._completed_steps = self._total_steps
    return await self._update_job(phase="validate", subphase="validation", status=status, result_json=result_json, expected_sections=expected_sections, section_progress=section_progress)

  async def fail(self, *, phase: str, message: str) -> JobRecord | None:
    """Set the job to an error state."""

    self.add_logs(message)
    self._completed_steps = self._total_steps
    payload = {"status": "error", "phase": phase, "subphase": "error", "progress": self._progress_percent(), "logs": self._logs}
    return await self._jobs_repo.update_job(self._job_id, **payload)

  @property
  def logs(self) -> list[str]:
    """Return a copy of the tracked logs."""

    return list(self._logs)
