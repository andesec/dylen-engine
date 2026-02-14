"""Runtime configuration services backed by Postgres."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

import sqlalchemy as sa
from app.config import Settings
from app.schema.runtime_config import RuntimeConfigScope, RuntimeConfigValue
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

ConfigValueType = Literal["bool", "int", "str", "json"]


@dataclass(frozen=True)
class RuntimeConfigDefinition:
  """Metadata used to validate and authorize runtime configuration keys."""

  key: str
  value_type: ConfigValueType
  description: str
  allowed_scopes: set[RuntimeConfigScope]
  super_admin_only: bool = False


_SCOPES_GLOBAL: set[RuntimeConfigScope] = {RuntimeConfigScope.GLOBAL}
_SCOPES_GLOBAL_TENANT: set[RuntimeConfigScope] = {RuntimeConfigScope.GLOBAL, RuntimeConfigScope.TENANT}
_SCOPES_GLOBAL_TIER_TENANT: set[RuntimeConfigScope] = {RuntimeConfigScope.GLOBAL, RuntimeConfigScope.TIER, RuntimeConfigScope.TENANT}
_SCOPES_TIER_TENANT: set[RuntimeConfigScope] = {RuntimeConfigScope.TIER, RuntimeConfigScope.TENANT}
_SCOPES_USER: set[RuntimeConfigScope] = {RuntimeConfigScope.USER}
_THEME_IDS: set[str] = {"essential_focus", "oceanic_logic", "deep_forest", "stochastic_library", "cliffside_serenity"}
_FENSTER_WIDGET_TIERS: set[str] = {"none", "flash", "reasoning"}

_RUNTIME_CONFIG_DEFINITIONS: dict[str, RuntimeConfigDefinition] = {
  "limits.max_topic_length": RuntimeConfigDefinition(key="limits.max_topic_length", value_type="int", description="Maximum topic length for lesson generation.", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.max_markdown_chars": RuntimeConfigDefinition(key="limits.max_markdown_chars", value_type="int", description="Maximum markdown length for MarkdownText widgets.", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "limits.lessons_per_week": RuntimeConfigDefinition(key="limits.lessons_per_week", value_type="int", description="Maximum lessons that may be generated per week.", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.sections_per_month": RuntimeConfigDefinition(key="limits.sections_per_month", value_type="int", description="Maximum lesson sections that may be generated per month.", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.tutor_sections_per_month": RuntimeConfigDefinition(key="limits.tutor_sections_per_month", value_type="int", description="Maximum tutor sections that may be generated per month.", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.fenster_widgets_per_month": RuntimeConfigDefinition(key="limits.fenster_widgets_per_month", value_type="int", description="Maximum Fenster widgets that may be generated per month.", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.ocr_files_per_month": RuntimeConfigDefinition(key="limits.ocr_files_per_month", value_type="int", description="Maximum OCR files that may be processed per month.", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.writing_checks_per_month": RuntimeConfigDefinition(key="limits.writing_checks_per_month", value_type="int", description="Maximum writing checks that may be requested per month.", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.history_lessons_kept": RuntimeConfigDefinition(key="limits.history_lessons_kept", value_type="int", description="Maximum recent lessons that remain available to the user.", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.max_file_upload_bytes": RuntimeConfigDefinition(key="limits.max_file_upload_bytes", value_type="int", description="Maximum file upload size in bytes (0 disables uploads).", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.youtube_capture_minutes_per_month": RuntimeConfigDefinition(key="limits.youtube_capture_minutes_per_month", value_type="int", description="Total YouTube capture minutes allowed per month.", allowed_scopes=_SCOPES_TIER_TENANT),
  "limits.image_generations_per_month": RuntimeConfigDefinition(key="limits.image_generations_per_month", value_type="int", description="Total image generations allowed per month.", allowed_scopes=_SCOPES_TIER_TENANT),
  "rights.user_owns_private_lessons": RuntimeConfigDefinition(key="rights.user_owns_private_lessons", value_type="bool", description="Whether the user owns private lessons they generate/upload within the app.", allowed_scopes=_SCOPES_TIER_TENANT),
  "marketplace.commission_percent": RuntimeConfigDefinition(key="marketplace.commission_percent", value_type="int", description="Commission percent for marketplace sales.", allowed_scopes=_SCOPES_TIER_TENANT),
  "career.mock_exams_token_cap": RuntimeConfigDefinition(key="career.mock_exams_token_cap", value_type="int", description="Token cap for mock exams.", allowed_scopes=_SCOPES_TIER_TENANT),
  "career.mock_exams_count": RuntimeConfigDefinition(key="career.mock_exams_count", value_type="int", description="Mock exams count cap.", allowed_scopes=_SCOPES_TIER_TENANT),
  "career.mock_interviews_enabled": RuntimeConfigDefinition(key="career.mock_interviews_enabled", value_type="bool", description="Enable mock interviews.", allowed_scopes=_SCOPES_TIER_TENANT),
  "career.mock_interviews_count": RuntimeConfigDefinition(key="career.mock_interviews_count", value_type="int", description="Mock interviews count cap.", allowed_scopes=_SCOPES_TIER_TENANT),
  "career.mock_interviews_minutes_cap": RuntimeConfigDefinition(key="career.mock_interviews_minutes_cap", value_type="int", description="Mock interviews minutes cap.", allowed_scopes=_SCOPES_TIER_TENANT),
  "tutor.passive_enabled": RuntimeConfigDefinition(key="tutor.passive_enabled", value_type="bool", description="Enable passive tutor.", allowed_scopes=_SCOPES_TIER_TENANT),
  "tutor.passive_lessons_cap": RuntimeConfigDefinition(key="tutor.passive_lessons_cap", value_type="int", description="Passive tutor lessons cap.", allowed_scopes=_SCOPES_TIER_TENANT),
  "tutor.active_enabled": RuntimeConfigDefinition(key="tutor.active_enabled", value_type="bool", description="Enable active tutor.", allowed_scopes=_SCOPES_TIER_TENANT),
  "tutor.active_tokens_per_month": RuntimeConfigDefinition(key="tutor.active_tokens_per_month", value_type="int", description="Active tutor token cap per month.", allowed_scopes=_SCOPES_TIER_TENANT),
  "features.disabled_global": RuntimeConfigDefinition(key="features.disabled_global", value_type="json", description="Feature flags disabled application-wide.", allowed_scopes=_SCOPES_GLOBAL, super_admin_only=True),
  "fenster.widgets_tier": RuntimeConfigDefinition(key="fenster.widgets_tier", value_type="str", description="Fenster widget tier (none|flash|reasoning).", allowed_scopes=_SCOPES_TIER_TENANT),
  "themes.allowed": RuntimeConfigDefinition(key="themes.allowed", value_type="json", description="Allowed theme IDs for the user.", allowed_scopes=_SCOPES_TIER_TENANT),
  "jobs.auto_process": RuntimeConfigDefinition(key="jobs.auto_process", value_type="bool", description="Automatically process jobs when created.", allowed_scopes=_SCOPES_GLOBAL_TENANT),
  "lessons.cache_catalog": RuntimeConfigDefinition(key="lessons.cache_catalog", value_type="bool", description="Enable cache headers for the lesson catalog.", allowed_scopes=_SCOPES_GLOBAL),
  "lessons.schema_version": RuntimeConfigDefinition(key="lessons.schema_version", value_type="str", description="Default schema version for generated lessons.", allowed_scopes=_SCOPES_GLOBAL, super_admin_only=True),
  "lessons.prompt_version": RuntimeConfigDefinition(key="lessons.prompt_version", value_type="str", description="Default prompt version for generated lessons.", allowed_scopes=_SCOPES_GLOBAL, super_admin_only=True),
  "lessons.repair_overlong_markdown": RuntimeConfigDefinition(key="lessons.repair_overlong_markdown", value_type="bool", description="Enable internal overlong markdown repair (USER-scope only).", allowed_scopes=_SCOPES_USER, super_admin_only=True),
  "ai.section_builder.model": RuntimeConfigDefinition(key="ai.section_builder.model", value_type="str", description="Default model for section builder (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.planner.model": RuntimeConfigDefinition(key="ai.planner.model", value_type="str", description="Default model for planner (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.outcomes.model": RuntimeConfigDefinition(key="ai.outcomes.model", value_type="str", description="Default model for outcomes agent (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.repair.model": RuntimeConfigDefinition(key="ai.repair.model", value_type="str", description="Default model for repair (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.fenster.model": RuntimeConfigDefinition(key="ai.fenster.model", value_type="str", description="Default model for Fenster builder (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.fenster.technical_constraints": RuntimeConfigDefinition(key="ai.fenster.technical_constraints", value_type="json", description="Fenster technical constraints JSON for widget generation.", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.writing.model": RuntimeConfigDefinition(key="ai.writing.model", value_type="str", description="Default model for writing checks (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.tutor.model": RuntimeConfigDefinition(key="ai.tutor.model", value_type="str", description="Default model for tutor (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.illustration.model": RuntimeConfigDefinition(key="ai.illustration.model", value_type="str", description="Default model for illustration (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.youtube.model": RuntimeConfigDefinition(key="ai.youtube.model", value_type="str", description="Default model for YouTube capture (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.research.model": RuntimeConfigDefinition(key="ai.research.model", value_type="str", description="Default model for research discovery (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "ai.research.router_model": RuntimeConfigDefinition(key="ai.research.router_model", value_type="str", description="Default router model for research intent classification (provider/model).", allowed_scopes=_SCOPES_GLOBAL_TIER_TENANT),
  "email.from_address": RuntimeConfigDefinition(key="email.from_address", value_type="str", description="Email 'from' address for outbound notifications.", allowed_scopes=_SCOPES_GLOBAL_TENANT),
  "email.from_name": RuntimeConfigDefinition(key="email.from_name", value_type="str", description="Email 'from' name for outbound notifications.", allowed_scopes=_SCOPES_GLOBAL_TENANT),
  "email.provider": RuntimeConfigDefinition(key="email.provider", value_type="str", description="Email provider identifier.", allowed_scopes=_SCOPES_GLOBAL),
  "email.mailersend.timeout_seconds": RuntimeConfigDefinition(key="email.mailersend.timeout_seconds", value_type="int", description="MailerSend timeout in seconds.", allowed_scopes=_SCOPES_GLOBAL),
  "email.mailersend.base_url": RuntimeConfigDefinition(key="email.mailersend.base_url", value_type="str", description="MailerSend API base URL.", allowed_scopes=_SCOPES_GLOBAL),
}


def list_runtime_config_definitions() -> list[RuntimeConfigDefinition]:
  """Return supported runtime config definitions for admin UIs."""
  # Return stable ordering so clients can cache render output.
  return [definition for _, definition in sorted(_RUNTIME_CONFIG_DEFINITIONS.items(), key=lambda item: item[0])]


def get_runtime_config_definition(key: str) -> RuntimeConfigDefinition:
  """Return the definition for a runtime config key or raise."""
  # Enforce allowlist so arbitrary keys cannot be persisted.
  normalized = (key or "").strip()
  if normalized not in _RUNTIME_CONFIG_DEFINITIONS:
    raise ValueError("Unknown runtime config key.")
  return _RUNTIME_CONFIG_DEFINITIONS[normalized]


def _validate_value(definition: RuntimeConfigDefinition, value: Any) -> Any:
  """Validate runtime config values based on the declared type."""
  # Keep validation strict so stored values remain predictable at runtime.
  if definition.value_type == "bool":
    if not isinstance(value, bool):
      raise ValueError("Value must be a boolean.")
    return value
  if definition.value_type == "int":
    if not isinstance(value, int):
      raise ValueError("Value must be an integer.")
    # For safety, reject negative quotas/caps so operators cannot invert enforcement.
    if definition.key != "limits.max_markdown_chars" and value < 0:
      raise ValueError("Value must be a non-negative integer.")
    # Enforce positive-only limits for markdown to avoid runtime crashes and DoS regressions.
    if definition.key == "limits.max_markdown_chars" and value <= 0:
      raise ValueError("Value must be a positive integer.")
    if definition.key == "marketplace.commission_percent" and value > 100:
      raise ValueError("Commission percent must be between 0 and 100.")
    return value
  if definition.value_type == "str":
    if not isinstance(value, str):
      raise ValueError("Value must be a string.")
    if value.strip() == "":
      raise ValueError("Value must be a non-empty string.")
    normalized = value.strip()
    if definition.key == "fenster.widgets_tier":
      if normalized.lower() not in _FENSTER_WIDGET_TIERS:
        raise ValueError("fenster.widgets_tier must be one of: none, flash, reasoning.")
      return normalized.lower()
    return normalized
  if definition.value_type == "json":
    if definition.key == "features.disabled_global":
      # Enforce list-of-strings for global feature disable list.
      if not isinstance(value, list) or any((not isinstance(item, str) or item.strip() == "") for item in value):
        raise ValueError("features.disabled_global must be a list of non-empty strings.")
      return [item.strip().lower() for item in value]
    if definition.key == "themes.allowed":
      # Validate theme allowlists so clients cannot be tricked into rendering unknown themes.
      if not isinstance(value, list) or any((not isinstance(item, str) or item.strip() == "") for item in value):
        raise ValueError("themes.allowed must be a list of non-empty strings.")
      normalized = [item.strip().lower() for item in value]
      invalid = [item for item in normalized if item not in _THEME_IDS]
      if invalid:
        raise ValueError("themes.allowed contains unknown theme IDs.")
      return normalized
    return value
  raise ValueError("Unsupported config value type.")


def _env_fallback(settings: Settings, key: str) -> Any:
  """Resolve a fallback value from environment-backed Settings for a config key."""
  # Preserve existing behavior by defaulting to environment settings when DB is unset.
  if key == "limits.max_topic_length":
    return 200  # Hardcoded default, no longer env-configurable
  if key == "limits.max_markdown_chars":
    return int(settings.max_markdown_chars)
  if key == "limits.lessons_per_week":
    return 0
  if key == "limits.sections_per_month":
    return 0
  if key == "limits.tutor_sections_per_month":
    return 0
  if key == "limits.fenster_widgets_per_month":
    return 0
  if key == "limits.ocr_files_per_month":
    return 0
  if key == "limits.writing_checks_per_month":
    return 0
  if key == "limits.history_lessons_kept":
    return 0
  if key == "limits.max_file_upload_bytes":
    return 0
  if key == "limits.youtube_capture_minutes_per_month":
    return 0
  if key == "limits.image_generations_per_month":
    return 0
  if key == "rights.user_owns_private_lessons":
    return False
  if key == "marketplace.commission_percent":
    return 0
  if key == "career.mock_exams_token_cap":
    return 0
  if key == "career.mock_exams_count":
    return 0
  if key == "career.mock_interviews_enabled":
    return False
  if key == "career.mock_interviews_count":
    return 0
  if key == "career.mock_interviews_minutes_cap":
    return 0
  if key == "tutor.passive_enabled":
    return False
  if key == "tutor.passive_lessons_cap":
    return 0
  if key == "tutor.active_enabled":
    return False
  if key == "tutor.active_tokens_per_month":
    return 0
  if key == "features.disabled_global":
    return []
  if key == "themes.allowed":
    return []
  if key == "fenster.widgets_tier":
    return "none"
  if key == "jobs.auto_process":
    return True  # Default to auto-process enabled
  if key == "lessons.cache_catalog":
    return False  # No caching by default (runtime configurable via DB)
  if key == "lessons.schema_version":
    return str(settings.schema_version)
  if key == "lessons.prompt_version":
    return str(settings.prompt_version)
  if key == "lessons.repair_overlong_markdown":
    return False
  if key == "ai.section_builder.model":
    return "gemini/gemini-2.5-flash"
  if key == "ai.planner.model":
    return "gemini/gemini-2.5-flash"
  if key == "ai.outcomes.model":
    return "gemini/gemini-2.5-flash"
  if key == "ai.repair.model":
    return "gemini/gemini-2.5-flash"
  if key == "ai.fenster.model":
    return "gemini/gemini-2.5-flash"
  if key == "ai.fenster.technical_constraints":
    return dict(settings.fenster_technical_constraints)
  if key == "ai.writing.model":
    return "gemini/gemini-2.5-flash"
  if key == "ai.tutor.model":
    return "gemini/gemini-2.5-flash"
  if key == "ai.illustration.model":
    return "gemini/gemini-2.5-flash-image"
  if key == "ai.youtube.model":
    return "gemini/gemini-2.0-flash"
  if key == "ai.research.model":
    return "gemini/gemini-2.0-flash"
  if key == "ai.research.router_model":
    return "gemini/gemini-2.0-flash"

  if key == "email.from_address":
    return str(settings.email_from_address or "")
  if key == "email.from_name":
    return str(settings.email_from_name or "")
  if key == "email.provider":
    return str(settings.email_provider)
  if key == "email.mailersend.timeout_seconds":
    return int(settings.mailersend_timeout_seconds)
  if key == "email.mailersend.base_url":
    return str(settings.mailersend_base_url)
  return None


async def _fetch_scope_values(session: AsyncSession, *, keys: list[str], scope: RuntimeConfigScope, org_id: uuid.UUID | None, subscription_tier_id: int | None, user_id: uuid.UUID | None) -> dict[str, Any]:
  """Fetch runtime config values for a specific scope."""
  # Build a query constrained to the target scope and identifier fields.
  stmt = select(RuntimeConfigValue.key, RuntimeConfigValue.value_json).where(RuntimeConfigValue.scope == scope, RuntimeConfigValue.key.in_(keys))
  if scope == RuntimeConfigScope.TENANT:
    stmt = stmt.where(RuntimeConfigValue.org_id == org_id)
  if scope == RuntimeConfigScope.TIER:
    stmt = stmt.where(RuntimeConfigValue.subscription_tier_id == subscription_tier_id)
  if scope == RuntimeConfigScope.USER:
    if user_id is None:
      return {}
    stmt = stmt.where(RuntimeConfigValue.user_id == user_id)
  result = await session.execute(stmt)
  return {str(row[0]): row[1] for row in result.fetchall()}


async def resolve_effective_runtime_config(session: AsyncSession, *, settings: Settings, org_id: uuid.UUID | None, subscription_tier_id: int | None, user_id: uuid.UUID | None = None) -> dict[str, Any]:
  """Resolve effective runtime config by merging env fallbacks, then DB overrides."""
  # Use allowlisted keys only so callers cannot request arbitrary config.
  keys = list(_RUNTIME_CONFIG_DEFINITIONS.keys())
  effective: dict[str, Any] = {key: _env_fallback(settings, key) for key in keys}

  # Apply global overrides first for broad defaults.
  global_values = await _fetch_scope_values(session, keys=keys, scope=RuntimeConfigScope.GLOBAL, org_id=None, subscription_tier_id=None, user_id=None)
  effective.update(global_values)

  # Apply tier overrides next so plans can differ by subscription.
  if subscription_tier_id is not None:
    tier_values = await _fetch_scope_values(session, keys=keys, scope=RuntimeConfigScope.TIER, org_id=None, subscription_tier_id=subscription_tier_id, user_id=None)
    effective.update(tier_values)

  # Apply tenant overrides last so org admins can customize within the tier.
  if org_id is not None:
    tenant_values = await _fetch_scope_values(session, keys=keys, scope=RuntimeConfigScope.TENANT, org_id=org_id, subscription_tier_id=None, user_id=None)
    effective.update(tenant_values)

  # Apply per-user overrides last so internal per-user controls remain narrowly scoped.
  if user_id is not None:
    user_values = await _fetch_scope_values(session, keys=keys, scope=RuntimeConfigScope.USER, org_id=None, subscription_tier_id=None, user_id=user_id)
    effective.update(user_values)

  return effective


async def upsert_runtime_config_value(session: AsyncSession, *, key: str, scope: RuntimeConfigScope, value: Any, org_id: uuid.UUID | None, subscription_tier_id: int | None, user_id: uuid.UUID | None = None) -> None:
  """Upsert a runtime config value into the DB for the specified scope."""
  definition = get_runtime_config_definition(key)
  if scope not in definition.allowed_scopes:
    raise ValueError("Scope is not allowed for this config key.")

  # Prevent creating ambiguous USER-scope rows with missing targets.
  if scope == RuntimeConfigScope.USER and user_id is None:
    raise ValueError("user_id is required for USER scope.")

  validated = _validate_value(definition, value)
  payload: dict[str, Any] = {"key": definition.key, "scope": scope, "org_id": org_id, "subscription_tier_id": subscription_tier_id, "user_id": user_id, "value_json": validated}

  # Target the correct partial unique index to keep scope uniqueness strict.
  if scope == RuntimeConfigScope.GLOBAL:
    stmt = insert(RuntimeConfigValue).values(payload).on_conflict_do_update(index_elements=["key"], index_where=sa.text("scope = 'GLOBAL'"), set_={"value_json": validated})
  elif scope == RuntimeConfigScope.TENANT:
    stmt = insert(RuntimeConfigValue).values(payload).on_conflict_do_update(index_elements=["key", "org_id"], index_where=sa.text("scope = 'TENANT'"), set_={"value_json": validated})
  elif scope == RuntimeConfigScope.TIER:
    stmt = insert(RuntimeConfigValue).values(payload).on_conflict_do_update(index_elements=["key", "subscription_tier_id"], index_where=sa.text("scope = 'TIER'"), set_={"value_json": validated})
  elif scope == RuntimeConfigScope.USER:
    stmt = insert(RuntimeConfigValue).values(payload).on_conflict_do_update(index_elements=["key", "user_id"], index_where=sa.text("scope = 'USER'"), set_={"value_json": validated})
  else:
    raise ValueError("Unsupported scope.")

  await session.execute(stmt)
  await session.commit()


async def list_runtime_config_values(session: AsyncSession, *, scope: RuntimeConfigScope, org_id: uuid.UUID | None, subscription_tier_id: int | None, user_id: uuid.UUID | None = None) -> dict[str, Any]:
  """List runtime config values explicitly set for a given scope."""
  keys = list(_RUNTIME_CONFIG_DEFINITIONS.keys())
  return await _fetch_scope_values(session, keys=keys, scope=scope, org_id=org_id, subscription_tier_id=subscription_tier_id, user_id=user_id)


def redact_super_admin_config(config: dict[str, Any]) -> dict[str, Any]:
  """Remove super-admin-only keys from a runtime config dict.

  Why:
    - Some internal config values (e.g., repair toggles) must not be exposed to end users.
    - Callers that serialize runtime config into user-facing payloads should use this helper.
  """
  redacted: dict[str, Any] = {}
  for key, value in config.items():
    definition = _RUNTIME_CONFIG_DEFINITIONS.get(key)
    if definition is not None and definition.super_admin_only:
      continue
    redacted[key] = value
  return redacted


# ============================================================================
# Model Configuration Helpers
# ============================================================================
# These helpers encapsulate the hierarchy and provider/model extraction logic.
# They simplify code that needs AI model configurations.


def _parse_provider_model(value: str | None, default_provider: str, default_model: str) -> tuple[str, str]:
  """Parse 'provider/model' format or return defaults.

  How/Why:
    - DB stores models as "provider/model" format (e.g., "gemini/gemini-2.5-flash")
    - This helper splits them and provides sensible defaults when missing
    - Callers get (provider, model) tuple directly without worrying about format
  """
  if not value:
    return (default_provider, default_model)

  value = str(value).strip()
  if "/" not in value:
    return (default_provider, value)

  parts = value.split("/", 1)
  provider = parts[0].strip() if parts[0].strip() else default_provider
  model = parts[1].strip() if len(parts) > 1 and parts[1].strip() else default_model

  return (provider, model)


def get_model_provider_and_name(runtime_config: dict[str, Any], config_key: str, default_provider: str, default_model: str) -> tuple[str, str]:
  """Get (provider, model) tuple from runtime config with defaults.

  How/Why:
    - Single call to get both provider and model from one config key
    - Automatically handles "provider/model" string format
    - Returns sensible defaults if not configured

  Example:
    provider, model = get_model_provider_and_name(
      runtime_config,
      "ai.section_builder.model",
      default_provider="gemini",
      default_model="gemini-2.5-flash"
    )
  """
  value = runtime_config.get(config_key)
  return _parse_provider_model(value, default_provider, default_model)


def get_section_builder_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for section builder."""
  return get_model_provider_and_name(runtime_config, "ai.section_builder.model", "gemini", "gemini-2.5-flash")


def get_planner_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for planner."""
  return get_model_provider_and_name(runtime_config, "ai.planner.model", "gemini", "gemini-2.5-flash")


def get_outcomes_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for outcomes agent."""
  return get_model_provider_and_name(runtime_config, "ai.outcomes.model", "gemini", "gemini-2.5-flash")


def get_repair_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for repair agent."""
  return get_model_provider_and_name(runtime_config, "ai.repair.model", "gemini", "gemini-2.5-flash")


def get_fenster_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for Fenster widget builder."""
  return get_model_provider_and_name(runtime_config, "ai.fenster.model", "gemini", "gemini-2.5-flash")


def get_writing_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for writing checks."""
  return get_model_provider_and_name(runtime_config, "ai.writing.model", "gemini", "gemini-2.5-flash")


def get_tutor_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for tutor."""
  return get_model_provider_and_name(runtime_config, "ai.tutor.model", "gemini", "gemini-2.5-flash")


def get_illustration_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for illustration/visualization."""
  return get_model_provider_and_name(runtime_config, "ai.illustration.model", "gemini", "gemini-2.5-flash-image")


def get_youtube_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for YouTube capture."""
  return get_model_provider_and_name(runtime_config, "ai.youtube.model", "gemini", "gemini-2.0-flash")


def get_research_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for research discovery."""
  return get_model_provider_and_name(runtime_config, "ai.research.model", "gemini", "gemini-2.0-flash")


def get_research_router_model(runtime_config: dict[str, Any]) -> tuple[str, str]:
  """Get (provider, model) for research router/classifier."""
  return get_model_provider_and_name(runtime_config, "ai.research.router_model", "gemini", "gemini-2.0-flash")
