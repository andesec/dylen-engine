"""Orchestration for the two-step AI pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.ai.providers.base import AIModel
from app.ai.router import get_model_for_mode
from app.schema.lesson_models import LessonDocument
from app.schema.widgets_loader import load_widget_registry


@dataclass(frozen=True)
class OrchestrationResult:
    """Output from the AI orchestration layer."""

    lesson_json: dict[str, Any]
    provider_a: str
    model_a: str
    provider_b: str
    model_b: str


class DgsOrchestrator:
    """Coordinates the gatherer and structurer agents."""

    def __init__(
        self,
        *,
        gatherer_provider: str,
        gatherer_model: str | None,
        structurer_provider: str,
        structurer_model: str | None,
        schema_version: str,
    ) -> None:
        self._gatherer_provider = gatherer_provider
        self._gatherer_model_name = gatherer_model
        self._structurer_provider = structurer_provider
        self._structurer_model_name = structurer_model
        self._schema_version = schema_version

    async def generate_lesson(
        self,
        *,
        topic: str,
        constraints: dict[str, Any] | None,
        schema_version: str | None = None,
        gatherer_model: str | None = None,
        structurer_model: str | None = None,
    ) -> OrchestrationResult:
        """Run the gatherer and structurer steps and return lesson JSON."""
        gatherer_model_name = gatherer_model or self._gatherer_model_name
        gatherer_model = get_model_for_mode(self._gatherer_provider, gatherer_model_name)
        gatherer_prompt = _render_gatherer_prompt(topic=topic, constraints=constraints)
        gatherer_response = await gatherer_model.generate(gatherer_prompt)

        structurer_model_name = structurer_model or self._structurer_model_name
        structurer_model = get_model_for_mode(self._structurer_provider, structurer_model_name)
        if not structurer_model.supports_structured_output:
            raise RuntimeError("Structured output is not available for the configured structurer.")

        structurer_prompt = _render_structurer_prompt(
            topic=topic,
            constraints=constraints,
            schema_version=schema_version or self._schema_version,
            idm=gatherer_response.content,
        )
        lesson_schema = _lesson_json_schema()
        lesson_json = await structurer_model.generate_structured(structurer_prompt, lesson_schema)
        return OrchestrationResult(
            lesson_json=lesson_json,
            provider_a=self._gatherer_provider,
            model_a=_model_name(gatherer_model),
            provider_b=self._structurer_provider,
            model_b=_model_name(structurer_model),
        )


def _model_name(model: AIModel) -> str:
    return getattr(model, "name", "unknown")


def _render_gatherer_prompt(*, topic: str, constraints: dict[str, Any] | None) -> str:
    prompt = _load_prompt("gatherer.md")
    return "\n".join(
        [
            prompt,
            f"Topic: {topic}",
            f"Constraints: {constraints or {}}",
        ]
    )


def _render_structurer_prompt(
    *,
    topic: str,
    constraints: dict[str, Any] | None,
    schema_version: str,
    idm: str,
) -> str:
    prompt = _load_prompt("structurer.md")
    widgets = _load_widgets_text()
    return "\n".join(
        [
            prompt,
            f"Topic: {topic}",
            f"Constraints: {constraints or {}}",
            f"Schema Version: {schema_version}",
            "Widgets:",
            widgets,
            "IDM:",
            idm,
        ]
    )


@lru_cache(maxsize=1)
def _load_prompt(name: str) -> str:
    path = Path(__file__).with_name("prompts") / name
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _load_widgets_text() -> str:
    path = Path(__file__).parents[1] / "schema" / "widgets.md"
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _lesson_json_schema() -> dict[str, Any]:
    json_schema = LessonDocument.model_json_schema()
    load_widget_registry(Path(__file__).parents[1] / "schema" / "widgets.md")
    return json_schema
