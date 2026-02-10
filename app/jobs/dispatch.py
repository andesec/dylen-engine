"""Dependency-injected job processor dispatch helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import Settings
from app.jobs.models import JobRecord
from app.services.tasks.interface import TaskEnqueuer
from app.storage.jobs_repo import JobsRepository


class JobProcessorHandler(Protocol):
  """Processor contract for a concrete target_agent implementation."""

  async def process(self, job: JobRecord) -> JobRecord | None:
    """Process one queued job record."""


@dataclass(frozen=True)
class JobProcessResult:
  """Result wrapper returned by the central dispatch function."""

  record: JobRecord | None


class JobProcessorRegistry:
  """Registry mapping target agents to processor handlers."""

  def __init__(self, handlers: dict[str, JobProcessorHandler]) -> None:
    self._handlers = handlers

  def resolve(self, target_agent: str) -> JobProcessorHandler:
    """Resolve the processor for a target agent."""
    handler = self._handlers.get(target_agent)
    if handler is None:
      raise ValueError(f"Unsupported target agent: {target_agent}")
    return handler


async def process_job(job: JobRecord, target_agent: str, registry: JobProcessorRegistry, jobs_repo: JobsRepository, enqueuer: TaskEnqueuer, quota_service: object, settings: Settings) -> JobProcessResult:
  """Dispatch a queued job to the correct handler via DI registry."""
  # Keep the function signature explicit so future job runners can inject custom collaborators.
  _ = (jobs_repo, enqueuer, quota_service, settings)
  handler = registry.resolve(target_agent)
  record = await handler.process(job)
  return JobProcessResult(record=record)
