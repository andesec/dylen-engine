"""Orchestrator factory."""

from __future__ import annotations

from app.ai.orchestrator import DgsOrchestrator
from app.config import Settings


def _get_orchestrator(
    settings: Settings,
    *,
    gatherer_provider: str | None = None,
    gatherer_model: str | None = None,
    planner_provider: str | None = None,
    planner_model: str | None = None,
    structurer_provider: str | None = None,
    structurer_model: str | None = None,
    repair_provider: str | None = None,
    repair_model: str | None = None,
) -> DgsOrchestrator:
    return DgsOrchestrator(
        gatherer_provider=gatherer_provider or settings.gatherer_provider,
        gatherer_model=gatherer_model or settings.gatherer_model,
        planner_provider=planner_provider or settings.planner_provider,
        planner_model=planner_model or settings.planner_model,
        structurer_provider=structurer_provider or settings.structurer_provider,
        structurer_model=structurer_model or settings.structurer_model,
        repair_provider=repair_provider or settings.repair_provider,
        repair_model=repair_model or settings.repair_model,
        schema_version=settings.schema_version,
        merge_gatherer_structurer=settings.merge_gatherer_structurer,
    )
