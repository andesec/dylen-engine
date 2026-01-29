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
_SCOPES_TIER_TENANT: set[RuntimeConfigScope] = {RuntimeConfigScope.TIER, RuntimeConfigScope.TENANT}

_RUNTIME_CONFIG_DEFINITIONS: dict[str, RuntimeConfigDefinition] = {
  "limits.max_topic_length": RuntimeConfigDefinition(key="limits.max_topic_length", value_type="int", description="Maximum topic length for lesson generation.", allowed_scopes=_SCOPES_TIER_TENANT),
  "jobs.auto_process": RuntimeConfigDefinition(key="jobs.auto_process", value_type="bool", description="Automatically process jobs when created.", allowed_scopes=_SCOPES_GLOBAL_TENANT),
  "jobs.ttl_seconds": RuntimeConfigDefinition(key="jobs.ttl_seconds", value_type="int", description="Optional TTL (seconds) for job records.", allowed_scopes=_SCOPES_GLOBAL),
  "jobs.max_retries": RuntimeConfigDefinition(key="jobs.max_retries", value_type="int", description="Maximum retry attempts for failed jobs.", allowed_scopes=_SCOPES_GLOBAL),
  "lessons.cache_catalog": RuntimeConfigDefinition(key="lessons.cache_catalog", value_type="bool", description="Enable cache headers for the lesson catalog.", allowed_scopes=_SCOPES_GLOBAL),
  "lessons.schema_version": RuntimeConfigDefinition(key="lessons.schema_version", value_type="str", description="Default schema version for generated lessons.", allowed_scopes=_SCOPES_GLOBAL, super_admin_only=True),
  "lessons.prompt_version": RuntimeConfigDefinition(key="lessons.prompt_version", value_type="str", description="Default prompt version for generated lessons.", allowed_scopes=_SCOPES_GLOBAL, super_admin_only=True),
  "ai.section_builder.provider": RuntimeConfigDefinition(key="ai.section_builder.provider", value_type="str", description="Default provider for section builder.", allowed_scopes=_SCOPES_TIER_TENANT),
  "ai.section_builder.model": RuntimeConfigDefinition(key="ai.section_builder.model", value_type="str", description="Default model for section builder.", allowed_scopes=_SCOPES_TIER_TENANT),
  "ai.planner.provider": RuntimeConfigDefinition(key="ai.planner.provider", value_type="str", description="Default provider for planner.", allowed_scopes=_SCOPES_TIER_TENANT),
  "ai.planner.model": RuntimeConfigDefinition(key="ai.planner.model", value_type="str", description="Default model for planner.", allowed_scopes=_SCOPES_TIER_TENANT),
  "ai.repair.provider": RuntimeConfigDefinition(key="ai.repair.provider", value_type="str", description="Default provider for repair.", allowed_scopes=_SCOPES_GLOBAL_TENANT),
  "ai.repair.model": RuntimeConfigDefinition(key="ai.repair.model", value_type="str", description="Default model for repair.", allowed_scopes=_SCOPES_GLOBAL_TENANT),
  "ai.fenster.provider": RuntimeConfigDefinition(key="ai.fenster.provider", value_type="str", description="Default provider for Fenster builder.", allowed_scopes=_SCOPES_TIER_TENANT),
  "ai.fenster.model": RuntimeConfigDefinition(key="ai.fenster.model", value_type="str", description="Default model for Fenster builder.", allowed_scopes=_SCOPES_TIER_TENANT),
  "ai.fenster.technical_constraints": RuntimeConfigDefinition(key="ai.fenster.technical_constraints", value_type="json", description="Fenster technical constraints JSON for widget generation.", allowed_scopes=_SCOPES_TIER_TENANT),
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
    return value
  if definition.value_type == "str":
    if not isinstance(value, str):
      raise ValueError("Value must be a string.")
    if value.strip() == "":
      raise ValueError("Value must be a non-empty string.")
    return value.strip()
  if definition.value_type == "json":
    return value
  raise ValueError("Unsupported config value type.")


def _env_fallback(settings: Settings, key: str) -> Any:
  """Resolve a fallback value from environment-backed Settings for a config key."""
  # Preserve existing behavior by defaulting to environment settings when DB is unset.
  if key == "limits.max_topic_length":
    return int(settings.max_topic_length)
  if key == "jobs.auto_process":
    return bool(settings.jobs_auto_process)
  if key == "jobs.ttl_seconds":
    return int(settings.jobs_ttl_seconds) if settings.jobs_ttl_seconds is not None else None
  if key == "jobs.max_retries":
    return int(settings.job_max_retries)
  if key == "lessons.cache_catalog":
    return bool(settings.cache_lesson_catalog)
  if key == "lessons.schema_version":
    return str(settings.schema_version)
  if key == "lessons.prompt_version":
    return str(settings.prompt_version)
  if key == "ai.section_builder.provider":
    return str(settings.section_builder_provider)
  if key == "ai.section_builder.model":
    return str(settings.section_builder_model or "")
  if key == "ai.planner.provider":
    return str(settings.planner_provider)
  if key == "ai.planner.model":
    return str(settings.planner_model or "")
  if key == "ai.repair.provider":
    return str(settings.repair_provider)
  if key == "ai.repair.model":
    return str(settings.repair_model or "")
  if key == "ai.fenster.provider":
    return str(settings.fenster_provider)
  if key == "ai.fenster.model":
    return str(settings.fenster_model or "")
  if key == "ai.fenster.technical_constraints":
    return dict(settings.fenster_technical_constraints)
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


async def _fetch_scope_values(session: AsyncSession, *, keys: list[str], scope: RuntimeConfigScope, org_id: uuid.UUID | None, subscription_tier_id: int | None) -> dict[str, Any]:
  """Fetch runtime config values for a specific scope."""
  # Build a query constrained to the target scope and identifier fields.
  stmt = select(RuntimeConfigValue.key, RuntimeConfigValue.value_json).where(RuntimeConfigValue.scope == scope, RuntimeConfigValue.key.in_(keys))
  if scope == RuntimeConfigScope.TENANT:
    stmt = stmt.where(RuntimeConfigValue.org_id == org_id)
  if scope == RuntimeConfigScope.TIER:
    stmt = stmt.where(RuntimeConfigValue.subscription_tier_id == subscription_tier_id)
  result = await session.execute(stmt)
  return {str(row[0]): row[1] for row in result.fetchall()}


async def resolve_effective_runtime_config(session: AsyncSession, *, settings: Settings, org_id: uuid.UUID | None, subscription_tier_id: int | None) -> dict[str, Any]:
  """Resolve effective runtime config by merging env fallbacks, then DB overrides."""
  # Use allowlisted keys only so callers cannot request arbitrary config.
  keys = list(_RUNTIME_CONFIG_DEFINITIONS.keys())
  effective: dict[str, Any] = {key: _env_fallback(settings, key) for key in keys}

  # Apply global overrides first for broad defaults.
  global_values = await _fetch_scope_values(session, keys=keys, scope=RuntimeConfigScope.GLOBAL, org_id=None, subscription_tier_id=None)
  effective.update(global_values)

  # Apply tier overrides next so plans can differ by subscription.
  if subscription_tier_id is not None:
    tier_values = await _fetch_scope_values(session, keys=keys, scope=RuntimeConfigScope.TIER, org_id=None, subscription_tier_id=subscription_tier_id)
    effective.update(tier_values)

  # Apply tenant overrides last so org admins can customize within the tier.
  if org_id is not None:
    tenant_values = await _fetch_scope_values(session, keys=keys, scope=RuntimeConfigScope.TENANT, org_id=org_id, subscription_tier_id=None)
    effective.update(tenant_values)

  return effective


async def upsert_runtime_config_value(session: AsyncSession, *, key: str, scope: RuntimeConfigScope, value: Any, org_id: uuid.UUID | None, subscription_tier_id: int | None) -> None:
  """Upsert a runtime config value into the DB for the specified scope."""
  definition = get_runtime_config_definition(key)
  if scope not in definition.allowed_scopes:
    raise ValueError("Scope is not allowed for this config key.")

  validated = _validate_value(definition, value)
  payload: dict[str, Any] = {"key": definition.key, "scope": scope, "org_id": org_id, "subscription_tier_id": subscription_tier_id, "value_json": validated}

  # Target the correct partial unique index to keep scope uniqueness strict.
  if scope == RuntimeConfigScope.GLOBAL:
    stmt = insert(RuntimeConfigValue).values(payload).on_conflict_do_update(index_elements=["key"], index_where=sa.text("scope = 'GLOBAL'"), set_={"value_json": validated})
  elif scope == RuntimeConfigScope.TENANT:
    stmt = insert(RuntimeConfigValue).values(payload).on_conflict_do_update(index_elements=["key", "org_id"], index_where=sa.text("scope = 'TENANT'"), set_={"value_json": validated})
  elif scope == RuntimeConfigScope.TIER:
    stmt = insert(RuntimeConfigValue).values(payload).on_conflict_do_update(index_elements=["key", "subscription_tier_id"], index_where=sa.text("scope = 'TIER'"), set_={"value_json": validated})
  else:
    raise ValueError("Unsupported scope.")

  await session.execute(stmt)
  await session.commit()


async def list_runtime_config_values(session: AsyncSession, *, scope: RuntimeConfigScope, org_id: uuid.UUID | None, subscription_tier_id: int | None) -> dict[str, Any]:
  """List runtime config values explicitly set for a given scope."""
  keys = list(_RUNTIME_CONFIG_DEFINITIONS.keys())
  return await _fetch_scope_values(session, keys=keys, scope=scope, org_id=org_id, subscription_tier_id=subscription_tier_id)
