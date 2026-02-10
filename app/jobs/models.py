"""Domain models for asynchronous lesson generation jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["queued", "running", "done", "error", "canceled"]
JobKind = Literal["lesson", "research", "youtube", "maintenance", "writing", "system"]


@dataclass
class JobRecord:
  """Represents a background lesson generation job."""

  job_id: str
  user_id: str | None
  job_kind: JobKind
  request: dict[str, Any]
  status: JobStatus
  created_at: str
  updated_at: str
  parent_job_id: str | None = None
  lesson_id: str | None = None
  section_id: int | None = None
  target_agent: str | None = None
  phase: str | None = None
  subphase: str | None = None
  expected_sections: int | None = None
  completed_sections: int | None = None
  completed_section_indexes: list[int] | None = None
  current_section_index: int | None = None
  current_section_status: str | None = None
  current_section_retry_count: int | None = None
  current_section_title: str | None = None
  retry_count: int | None = None
  max_retries: int | None = None
  retry_sections: list[int] | None = None
  retry_agents: list[str] | None = None
  retry_parent_job_id: str | None = None
  total_steps: int | None = None
  completed_steps: int | None = None
  progress: float | None = None
  logs: list[str] = field(default_factory=list)
  result_json: dict[str, Any] | None = None
  artifacts: dict[str, Any] | None = None
  validation: dict[str, Any] | None = None
  cost: dict[str, Any] | None = None
  completed_at: str | None = None
  ttl: int | None = None
  idempotency_key: str | None = None
