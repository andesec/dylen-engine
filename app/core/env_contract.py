"""Runtime environment contract checks for service and migrator processes.

How/Why:
- Keep runtime configuration explicit so deploy-time mistakes fail immediately.
- Prevent secret leakage by redacting sensitive values in startup logs.
- Share one registry between startup validation and deployment helper scripts.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

EnvUseTarget = Literal["service", "migrator", "both"]
EnvValidator = Callable[[str, dict[str, str]], str | None]


@dataclass(frozen=True)
class EnvVarDefinition:
  """Describe how and where an environment variable must be validated."""

  name: str
  required: bool
  secret: bool
  used_by: EnvUseTarget
  validator: EnvValidator | None = None


class EnvContractError(RuntimeError):
  """Raised when required runtime environment keys are missing or invalid."""


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
  """Parse boolean-ish environment values consistently for contract checks."""
  if raw is None:
    return default

  return raw.strip().lower() in {"1", "true", "yes", "on"}


def _validate_non_empty(value: str, _: dict[str, str]) -> str | None:
  """Ensure a value is not blank after trimming whitespace."""
  if value.strip() == "":
    return "must not be empty."

  return None


def _validate_allowed_origins(value: str, _: dict[str, str]) -> str | None:
  """Enforce strict CORS origins so wildcards cannot be introduced silently."""
  origins = [origin.strip() for origin in value.split(",") if origin.strip()]
  if not origins:
    return "must include at least one origin."

  if "*" in origins:
    return "must not include wildcard origins."

  return None


def _validate_environment_name(value: str, _: dict[str, str]) -> str | None:
  """Keep environment names predictable for deployment and startup controls."""
  normalized = value.strip().lower()
  if normalized in {"dev", "development", "stage", "staging", "prod", "production", "test", "testing"}:
    return None

  return "must be one of: development, stage, production, test (or aliases)."


def _validate_required_if_enabled(value: str, env_map: dict[str, str]) -> str | None:
  """Require dependent secrets only when feature toggles are explicitly enabled."""
  feature_enabled = _parse_bool(env_map.get("DYLEN_EMAIL_NOTIFICATIONS_ENABLED"))
  if not feature_enabled:
    return None

  if value.strip() == "":
    return "must be set when DYLEN_EMAIL_NOTIFICATIONS_ENABLED is true."

  return None


REQUIRED_ENV_REGISTRY: tuple[EnvVarDefinition, ...] = (
  EnvVarDefinition(name="DYLEN_ENV", required=True, secret=False, used_by="service", validator=_validate_environment_name),
  EnvVarDefinition(name="DYLEN_ALLOWED_ORIGINS", required=True, secret=False, used_by="service", validator=_validate_allowed_origins),
  EnvVarDefinition(name="DYLEN_PG_DSN", required=True, secret=True, used_by="both", validator=_validate_non_empty),
  EnvVarDefinition(name="GCP_PROJECT_ID", required=True, secret=False, used_by="service", validator=_validate_non_empty),
  EnvVarDefinition(name="GCP_LOCATION", required=True, secret=False, used_by="service", validator=_validate_non_empty),
  EnvVarDefinition(name="FIREBASE_PROJECT_ID", required=True, secret=False, used_by="service", validator=_validate_non_empty),
  EnvVarDefinition(name="DYLEN_ILLUSTRATION_BUCKET", required=True, secret=False, used_by="service", validator=_validate_non_empty),
  EnvVarDefinition(name="GEMINI_API_KEY", required=True, secret=True, used_by="service", validator=_validate_non_empty),
  EnvVarDefinition(name="OPENROUTER_API_KEY", required=True, secret=True, used_by="service", validator=_validate_non_empty),
  EnvVarDefinition(name="DYLEN_EMAIL_NOTIFICATIONS_ENABLED", required=False, secret=False, used_by="service"),
  EnvVarDefinition(name="DYLEN_MAILERSEND_API_KEY", required=False, secret=True, used_by="service", validator=_validate_required_if_enabled),
)


def _iter_applicable_definitions(*, target: Literal["service", "migrator"]) -> tuple[EnvVarDefinition, ...]:
  """Filter registry entries so each process validates only relevant keys."""
  applicable: list[EnvVarDefinition] = []
  for definition in REQUIRED_ENV_REGISTRY:
    if definition.used_by == "both" or definition.used_by == target:
      applicable.append(definition)

  return tuple(applicable)


def _resolve_value(*, definition: EnvVarDefinition) -> str:
  """Resolve values with explicit compatibility aliases for DB DSN migration."""
  raw = os.getenv(definition.name)
  if raw is not None:
    return raw

  if definition.name == "DYLEN_PG_DSN":
    return os.getenv("DATABASE_URL", "")

  return ""


def list_required_env_names(*, target: Literal["service", "migrator"]) -> tuple[str, ...]:
  """Expose required key names for deploy automation and script guardrails."""
  names: list[str] = []
  for definition in _iter_applicable_definitions(target=target):
    if definition.required:
      names.append(definition.name)

  return tuple(names)


def validate_env_values(*, target: Literal["service", "migrator"], env_map: dict[str, str]) -> list[str]:
  """Validate a provided env map against contract rules for a target process."""
  errors: list[str] = []
  applicable_definitions = _iter_applicable_definitions(target=target)
  for definition in applicable_definitions:
    value = env_map.get(definition.name, "")
    if definition.required and value.strip() == "":
      errors.append(f"{definition.name}: required variable is missing.")
      continue

    if definition.validator and value.strip() != "":
      validation_error = definition.validator(value, env_map)
      if validation_error:
        errors.append(f"{definition.name}: {validation_error}")

  return errors


def validate_runtime_env_or_raise(*, logger: logging.Logger, target: Literal["service", "migrator"]) -> None:
  """Validate and log runtime env values using the centralized contract."""
  # Default to False to allow CI/Test environments to verify image startup without full config.
  # Production environments should explicitly set DYLEN_ENV_CONTRACT_ENFORCE=1.
  env_contract_enabled = _parse_bool(os.getenv("DYLEN_ENV_CONTRACT_ENFORCE"), default=False)
  resolved_values: dict[str, str] = {}
  applicable_definitions = _iter_applicable_definitions(target=target)
  for definition in applicable_definitions:
    value = _resolve_value(definition=definition)
    resolved_values[definition.name] = value
    if definition.secret:
      logger.info("ENV_CHECK key=%s value=<redacted>", definition.name)
    else:
      if value == "":
        logger.info("ENV_CHECK key=%s value=<missing>", definition.name)
      else:
        logger.info("ENV_CHECK key=%s value=%s", definition.name, value)

  errors = validate_env_values(target=target, env_map=resolved_values)

  if not errors:
    logger.info("ENV_CHECK status=ok target=%s checked=%d", target, len(applicable_definitions))
    return

  message = "ENV_CHECK status=failed target={target} violations:\n- {errors}".format(target=target, errors="\n- ".join(errors))
  if env_contract_enabled:
    logger.error(message)
    raise EnvContractError(message)

  logger.warning("ENV_CHECK enforcement disabled by DYLEN_ENV_CONTRACT_ENFORCE=0")
  logger.warning(message)
