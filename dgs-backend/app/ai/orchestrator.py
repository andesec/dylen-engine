"""Orchestration for the two-step AI pipeline."""

from __future__ import annotations

import json
from collections.abc import Iterable
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
    logs: list[str]  # New field for tracking pipeline steps


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
        topic_details: str | None = None,
        constraints: dict[str, Any] | None = None,
        schema_version: str | None = None,
        structurer_model: str | None = None,
        gatherer_model: str | None = None,
        enable_repair: bool = True,
    ) -> OrchestrationResult:
        """Run the gatherer and structurer steps and return lesson JSON."""
        import logging
        logger = logging.getLogger(__name__)
        logs: list[str] = []
        
        # Log model selection
        gatherer_model_name = gatherer_model or self._gatherer_model_name
        structurer_model_name = structurer_model or self._structurer_model_name
        
        log_msg = f"Starting generation for topic: '{topic[:50]}...' if len >= 50 else topic"
        logs.append(log_msg)
        logger.info(log_msg)
        
        log_msg = f"Gatherer: {self._gatherer_provider}/{gatherer_model_name or 'default'}"
        logs.append(log_msg)
        logger.info(log_msg)
        
        # Step 1: Gatherer
        gatherer_model = get_model_for_mode(self._gatherer_provider, gatherer_model_name)
        gatherer_prompt = _render_gatherer_prompt(topic=topic, topic_details=topic_details, constraints=constraints)
        
        log_msg = "Running gatherer agent..."
        logs.append(log_msg)
        logger.info(log_msg)
        logger.debug(f"Gatherer Prompt:\n{gatherer_prompt}")

        
        try:
            gatherer_response = await gatherer_model.generate(gatherer_prompt)
        except Exception as e:
            logger.error(f"Gatherer failed: {e}", exc_info=True)
            raise RuntimeError(f"Gatherer agent failed: {e}") from e
        
        log_msg = f"Gatherer completed ({len(gatherer_response.content)} chars)"
        logs.append(log_msg)
        logger.info(log_msg)
        logger.debug(f"Gatherer Response:\n{gatherer_response.content}")


        # Step 2: Structurer
        log_msg = f"Structurer: {self._structurer_provider}/{structurer_model_name or 'default'}"
        logs.append(log_msg)
        logger.info(log_msg)
        
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
        
        # Sanitize schema for Gemini SDK (removes nullables and recursion that cause crashes)
        sanitized_schema = _sanitize_schema_for_gemini(lesson_schema)
        
        log_msg = "Running structurer agent..."
        logs.append(log_msg)
        logger.info(log_msg)
        logger.debug(f"Structurer Prompt (Structured):\n{structurer_prompt}")

        
        try:
            lesson_json = await structurer_model.generate_structured(structurer_prompt, sanitized_schema)
        except Exception as e:
            logger.warning(f"Structurer structured generation failed: {e}. Falling back to raw JSON generation.")
            # Fallback: Generate raw text and parse
            # Ensure the full schema is in the prompt for the fallback path
            schema_str = json.dumps(lesson_schema, indent=2)
            fallback_prompt = structurer_prompt + f"\n\nCRITICAL: Output ONLY valid JSON matching this schema:\n{schema_str}\n\nIMPORTANT CONSTRAINTS:\n1. All fields marked as required in the schema MUST be present.\n2. Respect exact widget structures (e.g. asciiDiagram must have lead and diagram).\n3. Keep strings within length limits defined in the schema.\n4. Do not include markdown code fences, headers, or any text other than the JSON object."
            logger.debug(f"Structurer Prompt (Fallback):\n{fallback_prompt}")
            
            raw_response = await structurer_model.generate(fallback_prompt)
            # Remove markdown code fences if present
            cleaned_json = raw_response.content.strip()
            
            logger.debug(f"Structurer Response (Fallback Raw):\n{cleaned_json}")
            
            if cleaned_json.startswith("```"):
                import re
                cleaned_json = re.sub(r"^```\w*\n|```$", "", cleaned_json, flags=re.MULTILINE).strip()
            
            try:
                lesson_json = json.loads(cleaned_json)
            except json.JSONDecodeError as json_err:
                logger.error(f"Fallback JSON parsing failed: {json_err}. Raw content: {raw_response.content[:200]}...", exc_info=True)
                raise RuntimeError(f"Structurer failed to generate valid JSON: {json_err}") from e
        
        log_msg = "Structurer completed, validating..."
        logs.append(log_msg)
        logger.info(log_msg)
        
        # Import validation and repair utilities
        from app.schema.validate_lesson import validate_lesson
        from app.ai.deterministic_repair import attempt_deterministic_repair, is_worth_ai_repair
        
        # Validate the generated lesson
        ok, errors, _ = validate_lesson(lesson_json)
        
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
            
            if ok_after_deterministic:
                log_msg = "✓ Deterministic repair succeeded"
                logs.append(log_msg)
                logger.info(log_msg)
            else:
                log_msg = f"Deterministic repair reduced errors to {len(errors_after_deterministic)}"
                logs.append(log_msg)
                logger.info(log_msg)
            
            # Step 2: If still invalid and errors are complex, use AI repair
            if not ok_after_deterministic and is_worth_ai_repair(errors_after_deterministic):
                log_msg = "Errors are complex, attempting AI repair..."
                logs.append(log_msg)
                logger.info(log_msg)
                
                repair_prompt = _render_repair_prompt(
                    topic=topic,
                    constraints=constraints,
                    invalid_json=repaired_json,
                    errors=errors_after_deterministic,
                    widgets_text=_load_widgets_text(),
                )
                # Use the dedicated repair model
                repair_model_name = self._repair_model_name or structurer_model_name
                repair_model = get_model_for_mode(self._repair_provider, repair_model_name)
                
                log_msg = f"Running repair with {self._repair_provider}/{repair_model_name or 'default'}..."
                logs.append(log_msg)
                logger.info(log_msg)
                
                try:
                    repaired_json = await repair_model.generate_structured(repair_prompt, lesson_schema)
                except Exception as e:
                    logger.error(f"Repair agent failed: {e}", exc_info=True)
                    # Don't crash on repair failure, just fallback to deterministic repair result
                    logger.warning("Falling back to deterministic repair result due to AI repair failure.")
                    repaired_json = lesson_json
                
                # Final validation
                ok_final, errors_final, _ = validate_lesson(repaired_json)
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
        
        return OrchestrationResult(
            lesson_json=lesson_json,
            provider_a=self._gatherer_provider,
            model_a=_model_name(gatherer_model),
            provider_b=self._structurer_provider,
            model_b=_model_name(structurer_model),
            logs=logs,
        )


def _model_name(model: AIModel) -> str:
    return getattr(model, "name", "unknown")


def _render_gatherer_prompt(*, topic: str, topic_details: str | None, constraints: dict[str, Any] | None) -> str:
    prompt = _load_prompt("gatherer.md")
    parts = [prompt, f"Topic: {topic}"]
    if topic_details:
        parts.append(f"Additional Details: {topic_details}")
    parts.append(f"Constraints: {constraints or {}}")
    return "\n".join(parts)


def _render_structurer_prompt(
    *,
    topic: str,
    constraints: dict[str, Any] | None,
    schema_version: str,
    idm: str,
) -> str:
    prompt = _load_prompt("structurer.md")
    # Note: We rely on the JSON schema passed to the API or fallback prompt for widget definitions
    return "\n".join(
        [
            prompt,
            f"Topic: {topic}",
            f"Constraints: {constraints or {}}",
            f"Schema Version: {schema_version}",
            "IDM:",
            idm,
        ]
    )


def _render_repair_prompt(
    *,
    topic: str,
    constraints: dict[str, Any] | None,
    invalid_json: dict[str, Any],
    errors: list[str],
    widgets_text: str,
) -> str:
    """Render the repair agent prompt with validation errors."""
    import json
    
    prompt = _load_prompt("repair.md")
    return "\n".join(
        [
            prompt,
            f"Topic: {topic}",
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
    json_schema = LessonDocument.model_json_schema()
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
                opt for opt in options 
                if not (isinstance(opt, dict) and opt.get("type") == "null")
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
