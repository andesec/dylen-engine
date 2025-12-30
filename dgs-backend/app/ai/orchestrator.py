"""Orchestration for the two-step AI pipeline."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

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
    validation_errors: list[str] | None = None
    logs: list[str] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)
    total_cost: float = 0.0


class DgsOrchestrator:
    """Coordinates the gatherer and structurer agents."""

    def __init__(
        self,
        *,
        gatherer_provider: str,
        gatherer_model: str | None,
        structurer_provider: str,
        structurer_model: str | None,
        repair_provider: str,
        repair_model: str | None,
        schema_version: str,
    ) -> None:
        self._gatherer_provider = gatherer_provider
        self._gatherer_model_name = gatherer_model
        self._structurer_provider = structurer_provider
        self._structurer_model_name = structurer_model
        self._repair_provider = repair_provider
        self._repair_model_name = repair_model
        self._schema_version = schema_version

    async def generate_lesson(
        self,
        *,
        topic: str,
        prompt: str | None = None,
        constraints: dict[str, Any] | None = None,
        schema_version: str | None = None,
        structurer_model: str | None = None,
        gatherer_model: str | None = None,
        structured_output: bool = True,
        language: str | None = None,
        enable_repair: bool = True,
        progress_callback: Callable[[str, list[str] | None], None] | None = None,
    ) -> OrchestrationResult:
        """Run the gatherer and structurer steps and return lesson JSON."""
        import logging

        logger = logging.getLogger(__name__)
        logs: list[str] = []
        all_usage: list[dict[str, Any]] = []
        validation_errors: list[str] | None = None
        
        def _report_progress(phase_name: str, msg: str) -> None:
            if progress_callback:
                progress_callback(phase_name, [msg])

        # Log model selection
        gatherer_model_name = gatherer_model or self._gatherer_model_name
        structurer_model_name = structurer_model or self._structurer_model_name

        log_msg = f"Starting generation for topic: '{topic[:50]}...' if len(topic) >= 50 else topic"
        logs.append(log_msg)
        logger.info(log_msg)

        log_msg = f"Gatherer: {self._gatherer_provider}/{gatherer_model_name or 'default'}"
        logs.append(log_msg)
        logger.info(log_msg)

        # Step 1: Gatherer
        gatherer_model_instance = get_model_for_mode(self._gatherer_provider, gatherer_model_name)
        gatherer_prompt = _render_gatherer_prompt(
            topic=topic,
            prompt=prompt,
            constraints=constraints,
            language=language,
        )

        def _report_progress(phase: str, message: str) -> None:
            if progress_callback:
                progress_callback(phase, [message])

        log_msg = "Running gatherer agent..."
        logs.append(log_msg)
        logger.info(log_msg)
        logger.debug(f"Gatherer Prompt:\n{gatherer_prompt}")

        try:
            gatherer_response = await gatherer_model_instance.generate(gatherer_prompt)
            if gatherer_response.usage:
                all_usage.append(
                    {"model": _model_name(gatherer_model_instance), "purpose": "gather", **gatherer_response.usage}
                )
        except Exception as e:
            logger.error(f"Gatherer failed: {e}", exc_info=True)
            raise RuntimeError(f"Gatherer agent failed: {e}") from e

        log_msg = f"Gatherer completed ({len(gatherer_response.content)} chars)"
        logs.append(log_msg)
        logger.info(log_msg)
        logger.debug(f"Gatherer Response:\n{gatherer_response.content}")
        _report_progress("collect", log_msg)

        lesson_schema = _lesson_json_schema()
        sanitized_schema = _sanitize_schema_for_gemini(lesson_schema)

        # 2. STRUCTURE PHASE
        length = (constraints or {}).get("length", "Highlights")
        sections_count = (constraints or {}).get("sections", 1)

        try:
            if length == "Training":
                lesson_json = await self._generate_training(
                    topic=topic,
                    prompt=prompt,
                    knowledge_base=knowledge_base,
                    sections_count=sections_count,
                    structurer=structurer_model_instance,
                    all_usage=all_usage,
                    logs=logs,
                    progress_callback=progress_callback,
                    language=language,
                )
            elif length == "Detailed":
                lesson_json = await self._generate_detailed(
                    topic=topic,
                    prompt=prompt,
                    knowledge_base=knowledge_base,
                    structurer=structurer_model_instance,
                    all_usage=all_usage,
                    logs=logs,
                    progress_callback=progress_callback,
                    language=language,
                )
            else:
                lesson_json = await self._generate_highlights(
                    topic=topic,
                    prompt=prompt,
                    knowledge_base=knowledge_base,
                    structurer=structurer_model_instance,
                    all_usage=all_usage,
                    logs=logs,
                    progress_callback=progress_callback,
                    language=language,
                    constraints=constraints,
                    schema_version=schema_version or self._schema_version,
                )
        except Exception as e:
            logger.error(f"Structure phase failed: {e}", exc_info=True)
            # Return partial result with usage so far
            total_cost = self._calculate_total_cost(all_usage)
            return OrchestrationResult(
                lesson_json={},
                provider_a=self._gatherer_provider,
                model_a=gatherer_model_name,
                provider_b=self._structurer_provider,
                model_b=structurer_model_name,
                logs=logs + [f"FAILED: {str(e)}"],
                usage=all_usage,
                total_cost=total_cost,
                validation_errors=[str(e)]
            )

        log_msg = "Structurer completed, validating..."
        logs.append(log_msg)
        logger.info(log_msg)
        _report_progress("transform", log_msg)

        # Import validation and repair utilities
        from app.ai.deterministic_repair import attempt_deterministic_repair, is_worth_ai_repair
        from app.schema.validate_lesson import validate_lesson

        # Validate the generated lesson
        ok, errors, _ = validate_lesson(lesson_json)
        validation_errors = errors

        if ok:
            log_msg = "✓ Validation passed on first attempt"
            logs.append(log_msg)
            logger.info(log_msg)
        else:
            log_msg = f"✗ Validation failed with {len(errors)} error(s)"
            logs.append(log_msg)
            logger.warning(log_msg)
            for error in errors[:3]:  # Log first 3 errors
                logger.warning(f"  - {error}")

        # Attempt repair if validation fails and repair is enabled
        if not ok and enable_repair and errors:
            # Step 1: Try deterministic repair first (no AI call)
            log_msg = "Attempting deterministic repair..."
            logs.append(log_msg)
            logger.info(log_msg)

            repaired_json = attempt_deterministic_repair(lesson_json, errors)

            # Re-validate after deterministic repair
            ok_after_deterministic, errors_after_deterministic, _ = validate_lesson(repaired_json)
            validation_errors = errors_after_deterministic

            if ok_after_deterministic:
                log_msg = "✓ Deterministic repair succeeded"
                logs.append(log_msg)
                logger.info(log_msg)
            else:
                log_msg = (
                    f"Deterministic repair reduced errors to {len(errors_after_deterministic)}"
                )
                logs.append(log_msg)
                logger.info(log_msg)

            # Step 2: If still invalid and errors are complex, use AI repair
            if not ok_after_deterministic and is_worth_ai_repair(errors_after_deterministic):
                log_msg = "Errors are complex, attempting AI repair..."
                logs.append(log_msg)
                logger.info(log_msg)

                repair_prompt = _render_repair_prompt(
                    topic=topic,
                    prompt=prompt,
                    constraints=constraints,
                    invalid_json=repaired_json,
                    errors=errors_after_deterministic,
                    widgets_text=_load_widgets_text(),
                )
                # Use the dedicated repair model
                repair_model_name = self._repair_model_name or structurer_model_name
                repair_model = get_model_for_mode(self._repair_provider, repair_model_name)

                log_msg = (
                    f"Running repair with {self._repair_provider}/"
                    f"{repair_model_name or 'default'}..."
                )
                logs.append(log_msg)
                logger.info(log_msg)

                try:
                    repair_response = await repair_model.generate_structured(
                        repair_prompt, lesson_schema
                    )
                    repaired_json = repair_response.content
                    if repair_response.usage:
                        all_usage.append(
                            {"model": _model_name(repair_model), "purpose": "repair", **repair_response.usage}
                        )
                except Exception as e:
                    logger.error(f"Repair agent failed: {e}", exc_info=True)
                    # Don't crash on repair failure, just fallback to deterministic repair result
                    logger.warning(
                        "Falling back to deterministic repair result due to AI repair failure."
                    )
                    # Keep the deterministically repaired JSON if AI repair fails
                    # repaired_json is already set to the deterministically repaired version
                    pass

                # Final validation
                ok_final, errors_final, _ = validate_lesson(repaired_json)
                validation_errors = errors_final
                if ok_final:
                    log_msg = "✓ AI repair succeeded"
                    logs.append(log_msg)
                    logger.info(log_msg)
                else:
                    log_msg = f"AI repair completed, {len(errors_final)} error(s) remain"
                    logs.append(log_msg)
                    logger.warning(log_msg)
            elif not ok_after_deterministic:
                log_msg = "Errors are simple, skipping AI repair"
                logs.append(log_msg)
                logger.info(log_msg)

            lesson_json = repaired_json

        log_msg = "Generation pipeline complete"
        logs.append(log_msg)
        logger.info(log_msg)

        total_cost = self._calculate_total_cost(all_usage)

        return OrchestrationResult(
            lesson_json=lesson_json,
            provider_a=self._gatherer_provider,
            model_a=_model_name(gatherer_model_instance),
            provider_b=self._structurer_provider,
            model_b=_model_name(structurer_model_instance),
            validation_errors=validation_errors if validation_errors else None,
            logs=logs,
            usage=all_usage,
            total_cost=total_cost,
        )

    def _calculate_total_cost(self, usage: list[dict[str, Any]]) -> float:
        """Estimate total cost based on token usage."""
        # Simple pricing map (per 1M tokens)
        PRICES = {
            "gemini-1.5-flash": (0.075, 0.30),
            "gemini-2.0-flash": (0.075, 0.30),
            "gemini-2.0-flash-exp": (0.0, 0.0),  # Free during preview
            "openai/gpt-4o-mini": (0.15, 0.60),
            "openai/gpt-4o": (5.0, 15.0),
            "anthropic/claude-3.5-sonnet": (3.0, 15.0),
        }

        total = 0.0
        for entry in usage:
            model = entry.get("model", "")
            p_in, p_out = PRICES.get(model, (0.5, 1.5))  # Default conservative pricing
            
            in_tokens = entry.get("prompt_tokens", 0)
            out_tokens = entry.get("completion_tokens", 0)
            
            total += (in_tokens / 1_000_000) * p_in
            total += (out_tokens / 1_000_000) * p_out
            
        return total

    async def _generate_highlights(
        self,
        topic: str,
        prompt: str | None,
        knowledge_base: str,
        structurer: AIModel,
        all_usage: list[dict[str, Any]],
        logs: list[str],
        progress_callback: Callable[[str, list[str] | None], None] | None,
        language: str | None,
        constraints: dict[str, Any] | None,
        schema_version: str,
    ) -> dict[str, Any]:
        """Generate a Highlights lesson in a single pass."""
        if progress_callback:
            progress_callback("transform", ["Structuring Highlights lesson..."])

        prompt_text = _render_structurer_prompt(
            topic=topic,
            prompt=prompt,
            constraints=constraints,
            schema_version=schema_version,
            idm=knowledge_base,
            language=language,
        )
        
        # We can reuse the unstructured logic if needed, but for now we use structured
        schema = _lesson_json_schema()
        sanitized = _sanitize_schema_for_gemini(schema)
        
        if structurer.supports_structured_output:
            res = await structurer.generate_structured(prompt_text, sanitized)
            if res.usage:
                all_usage.append({"model": _model_name(structurer), "purpose": "structure_highlights", **res.usage})
            return res.content
        else:
            # Fallback (simplified for brevity here)
            raw = await structurer.generate(prompt_text + "\n\nOutput ONLY valid JSON.")
            if raw.usage:
                all_usage.append({"model": _model_name(structurer), "purpose": "structure_highlights_raw", **raw.usage})
            return cast(dict[str, Any], json.loads(raw.content))

    async def _generate_detailed(
        self,
        topic: str,
        prompt: str | None,
        knowledge_base: str,
        structurer: AIModel,
        all_usage: list[dict[str, Any]],
        logs: list[str],
        progress_callback: Callable[[str, list[str] | None], None] | None,
        language: str | None,
    ) -> dict[str, Any]:
        """Generate a Detailed lesson in two passes."""
        # Pass 1: Skeleton and first part
        if progress_callback:
            progress_callback("transform", ["Structuring Detailed lesson (Call 1/2)..."])
            
        # For simplicity in this implementation, we do one full generation and one expansion/detail call
        full_res = await self._generate_highlights(
            topic=topic, prompt=prompt, knowledge_base=knowledge_base, 
            structurer=structurer, all_usage=all_usage, logs=logs, 
            progress_callback=None, language=language, 
            constraints={"length": "Detailed"}, schema_version=self._schema_version
        )
        
        if progress_callback:
            progress_callback("transform", ["Expanding content details (Call 2/2)..."])
            
        expand_prompt = f"Expand the following lesson with more detailed activities and deep-dive content:\n{json.dumps(full_res)}"
        res = await structurer.generate_structured(expand_prompt, _sanitize_schema_for_gemini(_lesson_json_schema()))
        if res.usage:
            all_usage.append({"model": _model_name(structurer), "purpose": "structure_detailed_expand", **res.usage})
            
        return res.content

    async def _generate_training(
        self,
        topic: str,
        prompt: str | None,
        knowledge_base: str,
        sections_count: int,
        structurer: AIModel,
        all_usage: list[dict[str, Any]],
        logs: list[str],
        progress_callback: Callable[[str, list[str] | None], None] | None,
        language: str | None,
    ) -> dict[str, Any]:
        """Generate a Training lesson by looping over sections."""
        if progress_callback:
            progress_callback("transform", [f"Planning {sections_count} sections..."])
            
        # 1. Plan sections
        plan_prompt = f"Based on this knowledge: {knowledge_base[:2000]}, plan {sections_count} section titles for a lesson on {topic}."
        plan_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "sections": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}}}}
            }
        }
        res_plan = await structurer.generate_structured(plan_prompt, _sanitize_schema_for_gemini(plan_schema))
        if res_plan.usage:
            all_usage.append({"model": _model_name(structurer), "purpose": "structure_training_plan", **res_plan.usage})
            
        # 2. Generate sections
        final_sections = []
        for i in range(sections_count):
            title = res_plan.content["sections"][i]["title"] if i < len(res_plan.content["sections"]) else f"Section {i+1}"
            if progress_callback:
                progress_callback("transform", [f"Generating section {i+1}/{sections_count}: {title}"])
                
            sec_prompt = f"Generate a detailed content section for '{title}' within a lesson on {topic}. Knowledge: {knowledge_base[:1000]}"
            # Simplified section content schema
            sec_res = await structurer.generate_structured(sec_prompt, {"type": "object", "properties": {"content": {"type": "string"}}})
            if sec_res.usage:
                all_usage.append({"model": _model_name(structurer), "purpose": f"structure_training_sec_{i+1}", **sec_res.usage})
            
            final_sections.append({"title": title, "content": sec_res.content.get("content", "")})
            
        return {
            "title": res_plan.content.get("title", topic),
            "sections": final_sections,
            "meta": {"topic": topic}
        }


def _model_name(model: AIModel) -> str:
    return getattr(model, "name", "unknown")


def _render_gatherer_prompt(
    *,
    topic: str,
    prompt: str | None,
    constraints: dict[str, Any] | None,
    language: str | None,
) -> str:
    prompt_template = _load_prompt("gatherer.md")
    parts = [prompt_template, f"Topic: {topic}"]
    if prompt:
        parts.append(f"User Prompt: {prompt}")
    if language:
        parts.append(f"Language: {language}")
    parts.append(f"Constraints: {constraints or {}}")
    return "\n".join(parts)


def _render_structurer_prompt(
    *,
    topic: str,
    prompt: str | None,
    constraints: dict[str, Any] | None,
    schema_version: str,
    idm: str,
    language: str | None,
) -> str:
    prompt_template = _load_prompt("structurer.md")
    # Note: We rely on the JSON schema passed to the API or fallback prompt for widget definitions
    return "\n".join(
        [
            prompt_template,
            f"Topic: {topic}",
            f"User Prompt: {prompt or ''}",
            f"Language: {language or ''}",
            f"Constraints: {constraints or {}}",
            f"Schema Version: {schema_version}",
            "IDM:",
            idm,
        ]
    )


def _render_repair_prompt(
    *,
    topic: str,
    prompt: str | None,
    constraints: dict[str, Any] | None,
    invalid_json: dict[str, Any],
    errors: list[str],
    widgets_text: str,
) -> str:
    """Render the repair agent prompt with validation errors."""
    import json

    prompt_template = _load_prompt("repair.md")
    return "\n".join(
        [
            prompt_template,
            f"Topic: {topic}",
            f"User Prompt: {prompt or ''}",
            f"Constraints: {constraints or {}}",
            "Widgets:",
            widgets_text,
            "\nInvalid JSON:",
            json.dumps(invalid_json, indent=2),
            "\nValidation Errors:",
            "\n".join(f"- {error}" for error in errors),
            "\nProvide the corrected JSON:",
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
    json_schema: dict[str, Any] = LessonDocument.model_json_schema()
    load_widget_registry(Path(__file__).parents[1] / "schema" / "widgets.md")
    return json_schema


def _sanitize_schema_for_gemini(schema: Any) -> Any:
    """
    Sanitize JSON schema for Gemini SDK compatibility.

    1. Removes 'null' from anyOf/type (Gemini SDK crashes on null types).
    2. Simplifies schemas that are just a single type union.
    3. Heuristically identifies and breaks recursion where possible (SDK RecursionError).
    """
    if not isinstance(schema, dict):
        if isinstance(schema, list):
            return [_sanitize_schema_for_gemini(item) for item in schema]
        return schema

    # Clone to avoid mutating the original
    cleaned = dict(schema)

    # 1. Handle anyOf/oneOf (remove nulls)
    for key in ("anyOf", "oneOf"):
        if key in cleaned:
            options = cleaned[key]
            # Remove null entries
            filtered = [
                opt for opt in options if not (isinstance(opt, dict) and opt.get("type") == "null")
            ]
            if len(filtered) == 1:
                # If only one remains, collapse it
                res = _sanitize_schema_for_gemini(filtered[0])
                # Merge into cleaned, but remove the original union key
                cleaned.pop(key)
                cleaned.update(res)
            else:
                cleaned[key] = [_sanitize_schema_for_gemini(item) for item in filtered]

    # 2. Convert type: [type, null] to type: type
    if isinstance(cleaned.get("type"), list):
        types = [t for t in cleaned["type"] if t != "null"]
        if len(types) == 1:
            cleaned["type"] = types[0]
        else:
            cleaned["type"] = types

    # Recursive cleaning
    for k, v in cleaned.items():
        if k not in ("anyOf", "oneOf"):  # Already handled
            cleaned[k] = _sanitize_schema_for_gemini(v)

    return cleaned
