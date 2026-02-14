"""Application configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.utils.env import default_env_path, load_env_file

load_env_file(default_env_path(), override=False)


@dataclass(frozen=True)
class Settings:
  """Typed settings for the Dylen service."""

  environment: str
  backup_dir: str
  allowed_origins: tuple[str, ...]
  debug: bool
  max_markdown_chars: int
  log_max_bytes: int
  log_backup_count: int
  log_http_4xx: bool
  log_http_bodies: bool
  log_http_body_bytes: int
  illustration_bucket: str
  export_bucket: str | None
  export_object_prefix: str
  export_signed_url_ttl_seconds: int
  export_max_zip_bytes: int | None
  gcs_storage_host: str | None
  fenster_technical_constraints: dict[str, Any] = field(hash=False)
  research_search_max_results: int
  prompt_version: str
  schema_version: str
  pg_dsn: str | None
  pg_connect_timeout: int
  llm_audit_enabled: bool
  gcp_project_id: str | None
  gcp_location: str | None
  firebase_project_id: str | None
  firebase_service_account_json_path: str | None
  superadmin_email: str | None
  email_notifications_enabled: bool
  email_from_address: str | None
  email_from_name: str | None
  email_provider: str
  mailersend_api_key: str | None
  mailersend_timeout_seconds: int
  mailersend_base_url: str
  push_notifications_enabled: bool
  push_vapid_public_key: str | None
  push_vapid_private_key: str | None
  push_vapid_sub: str | None
  tavily_api_key: str | None
  cloud_tasks_queue_path: str | None
  task_service_provider: str
  base_url: str | None
  internal_service_url: str | None
  gemini_api_key: str | None
  task_secret: str | None
  cloud_run_invoker_service_account: str | None


@dataclass(frozen=True)
class DatabaseSettings:
  """Typed settings for database connectivity and table naming."""

  debug: bool
  pg_dsn: str | None
  pg_connect_timeout: int


def _parse_origins(raw: str | None) -> tuple[str, ...]:
  if not raw:
    raise ValueError("DYLEN_ALLOWED_ORIGINS must be set to one or more origins.")

  origins = [origin.strip() for origin in raw.split(",") if origin.strip()]

  if not origins:
    raise ValueError("DYLEN_ALLOWED_ORIGINS must include at least one origin.")

  if "*" in origins:
    raise ValueError("DYLEN_ALLOWED_ORIGINS must not include wildcard origins.")

  return tuple(origins)


def _parse_json_dict(raw: str | None, default: dict[str, Any]) -> dict[str, Any]:
  if not raw:
    return default
  try:
    return json.loads(raw)
  except json.JSONDecodeError:
    return default


def _parse_bool(raw: str | None) -> bool:
  """Parse a boolean-ish string from environment variables."""

  if raw is None:
    return False

  normalized = raw.strip().lower()
  return normalized in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
  """Load settings once per process."""

  environment = os.getenv("DYLEN_ENV", "development").lower()
  backup_dir = os.getenv("DYLEN_BACKUP_DIR", "./backups").strip()

  # Toggle verbose error output and diagnostics in non-production environments.
  debug = _parse_bool(os.getenv("DYLEN_DEBUG"))

  max_markdown_chars = int(os.getenv("DYLEN_MAX_MARKDOWN_CHARS", "1500"))
  if max_markdown_chars <= 0:
    raise ValueError("DYLEN_MAX_MARKDOWN_CHARS must be a positive integer.")

  log_max_bytes = int(os.getenv("DYLEN_LOG_MAX_BYTES", "5242880"))  # 5MB default
  if log_max_bytes <= 0:
    raise ValueError("DYLEN_LOG_MAX_BYTES must be a positive integer.")

  log_backup_count = int(os.getenv("DYLEN_LOG_BACKUP_COUNT", "10"))
  if log_backup_count < 0:
    raise ValueError("DYLEN_LOG_BACKUP_COUNT must be zero or a positive integer.")

  # Allow opt-in logging of 4xx HTTPExceptions for diagnostics.
  log_http_4xx = _parse_bool(os.getenv("DYLEN_LOG_HTTP_4XX"))
  # Allow opt-in logging of HTTP request/response bodies with a size cap.
  log_http_bodies = _parse_bool(os.getenv("DYLEN_LOG_HTTP_BODIES"))
  log_http_body_bytes = int(os.getenv("DYLEN_LOG_HTTP_BODY_BYTES", "2048"))
  if log_http_body_bytes <= 0:
    raise ValueError("DYLEN_LOG_HTTP_BODY_BYTES must be a positive integer.")

  email_notifications_enabled = _parse_bool(os.getenv("DYLEN_EMAIL_NOTIFICATIONS_ENABLED"))
  email_from_address = _optional_str(os.getenv("DYLEN_EMAIL_FROM_ADDRESS"))
  email_from_name = _optional_str(os.getenv("DYLEN_EMAIL_FROM_NAME"))
  email_provider = (os.getenv("DYLEN_EMAIL_PROVIDER") or "mailersend").strip().lower()
  mailersend_api_key = _optional_str(os.getenv("DYLEN_MAILERSEND_API_KEY"))
  mailersend_timeout_seconds = int(os.getenv("DYLEN_MAILERSEND_TIMEOUT_SECONDS", "10"))
  mailersend_base_url = (os.getenv("DYLEN_MAILERSEND_BASE_URL") or "https://api.mailersend.com/v1").strip()
  push_notifications_enabled = _parse_bool(os.getenv("DYLEN_PUSH_NOTIFICATIONS_ENABLED"))
  push_vapid_public_key = _optional_str(os.getenv("DYLEN_PUSH_VAPID_PUBLIC_KEY"))
  push_vapid_private_key = _optional_str(os.getenv("DYLEN_PUSH_VAPID_PRIVATE_KEY"))
  push_vapid_sub = _optional_str(os.getenv("DYLEN_PUSH_VAPID_SUB"))
  export_signed_url_ttl_seconds = int(os.getenv("DYLEN_EXPORT_SIGNED_URL_TTL_SECONDS", "900"))
  if export_signed_url_ttl_seconds <= 0:
    raise ValueError("DYLEN_EXPORT_SIGNED_URL_TTL_SECONDS must be a positive integer.")
  export_max_zip_bytes = _parse_optional_int(os.getenv("DYLEN_EXPORT_MAX_ZIP_BYTES"))

  # Validate notification settings only when notifications are enabled.
  if email_notifications_enabled:
    if not email_from_address:
      raise ValueError("DYLEN_EMAIL_FROM_ADDRESS must be set when email notifications are enabled.")

    if email_provider != "mailersend":
      raise ValueError("DYLEN_EMAIL_PROVIDER must be 'mailersend'.")

    if not mailersend_api_key:
      raise ValueError("DYLEN_MAILERSEND_API_KEY must be set when email notifications are enabled.")

    if mailersend_timeout_seconds <= 0:
      raise ValueError("DYLEN_MAILERSEND_TIMEOUT_SECONDS must be a positive integer.")

  # Validate push configuration only when push notifications are enabled.
  if push_notifications_enabled:
    if not push_vapid_public_key:
      raise ValueError("DYLEN_PUSH_VAPID_PUBLIC_KEY must be set when push notifications are enabled.")

    if not push_vapid_private_key:
      raise ValueError("DYLEN_PUSH_VAPID_PRIVATE_KEY must be set when push notifications are enabled.")

    if not push_vapid_sub:
      raise ValueError("DYLEN_PUSH_VAPID_SUB must be set when push notifications are enabled.")

    if not (push_vapid_sub.startswith("mailto:") or push_vapid_sub.startswith("https://")):
      raise ValueError("DYLEN_PUSH_VAPID_SUB must start with 'mailto:' or 'https://'.")

  # AI models are now managed via runtime_config_values database table
  # Research search limit is still configured via env for backward compatibility
  research_search_max_results = int(os.getenv("DYLEN_RESEARCH_SEARCH_MAX_RESULTS", "5"))

  return Settings(
    environment=environment,
    backup_dir=backup_dir,
    allowed_origins=_parse_origins(os.getenv("DYLEN_ALLOWED_ORIGINS")),
    debug=debug,
    max_markdown_chars=max_markdown_chars,
    log_max_bytes=log_max_bytes,
    log_backup_count=log_backup_count,
    log_http_4xx=log_http_4xx,
    log_http_bodies=log_http_bodies,
    log_http_body_bytes=log_http_body_bytes,
    illustration_bucket=os.getenv("DYLEN_ILLUSTRATION_BUCKET", "dylen-illustrations"),
    export_bucket=_optional_str(os.getenv("DYLEN_EXPORT_BUCKET")),
    export_object_prefix=(os.getenv("DYLEN_EXPORT_OBJECT_PREFIX") or "data-transfer").strip(),
    export_signed_url_ttl_seconds=export_signed_url_ttl_seconds,
    export_max_zip_bytes=export_max_zip_bytes,
    gcs_storage_host=_optional_str(os.getenv("GCS_STORAGE_HOST")),
    fenster_technical_constraints=_parse_json_dict(os.getenv("DYLEN_FENSTER_TECHNICAL_CONSTRAINTS"), {"max_tokens": 4000, "allowed_libs": ["alpine", "tailwind"]}),
    research_search_max_results=research_search_max_results,
    prompt_version=os.getenv("DYLEN_PROMPT_VERSION", "v1"),
    schema_version=os.getenv("DYLEN_SCHEMA_VERSION", "1.0"),
    pg_dsn=os.getenv("DYLEN_PG_DSN") or os.getenv("DATABASE_URL"),
    pg_connect_timeout=int(os.getenv("DYLEN_PG_CONNECT_TIMEOUT", "5")),
    llm_audit_enabled=_parse_bool(os.getenv("DYLEN_LLM_AUDIT_ENABLED")),
    gcp_project_id=os.getenv("GCP_PROJECT_ID"),
    gcp_location=os.getenv("GCP_LOCATION"),
    firebase_project_id=os.getenv("FIREBASE_PROJECT_ID"),
    firebase_service_account_json_path=os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON_PATH"),
    superadmin_email=_optional_str(os.getenv("DYLEN_SUPERADMIN_EMAIL")),
    email_notifications_enabled=email_notifications_enabled,
    email_from_address=email_from_address,
    email_from_name=email_from_name,
    email_provider=email_provider,
    mailersend_api_key=mailersend_api_key,
    mailersend_timeout_seconds=mailersend_timeout_seconds,
    mailersend_base_url=mailersend_base_url,
    push_notifications_enabled=push_notifications_enabled,
    push_vapid_public_key=push_vapid_public_key,
    push_vapid_private_key=push_vapid_private_key,
    push_vapid_sub=push_vapid_sub,
    tavily_api_key=_optional_str(os.getenv("TAVILY_API_KEY")),
    cloud_tasks_queue_path=_optional_str(os.getenv("DYLEN_CLOUD_TASKS_QUEUE_PATH")),
    task_service_provider=os.getenv("DYLEN_TASK_SERVICE_PROVIDER", "local-http").lower(),
    base_url=_optional_str(os.getenv("DYLEN_BASE_URL")),
    internal_service_url=_optional_str(os.getenv("DYLEN_INTERNAL_SERVICE_URL")),
    gemini_api_key=_optional_str(os.getenv("GEMINI_API_KEY")),
    task_secret=_optional_str(os.getenv("DYLEN_TASK_SECRET")),
    cloud_run_invoker_service_account=_optional_str(os.getenv("DYLEN_CLOUD_RUN_INVOKER_SERVICE_ACCOUNT")),
  )


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
  """Load database settings without requiring web-runtime configuration like CORS."""
  # Keep database configuration isolated so migrations and offline scripts don't require unrelated env vars.
  debug = _parse_bool(os.getenv("DYLEN_DEBUG"))
  pg_connect_timeout = int(os.getenv("DYLEN_PG_CONNECT_TIMEOUT", "5"))
  if pg_connect_timeout <= 0:
    raise ValueError("DYLEN_PG_CONNECT_TIMEOUT must be a positive integer.")

  # Support fallback to DATABASE_URL for backward compatibility
  pg_dsn = os.getenv("DYLEN_PG_DSN") or os.getenv("DATABASE_URL")

  return DatabaseSettings(debug=debug, pg_dsn=pg_dsn, pg_connect_timeout=pg_connect_timeout)


def _optional_str(raw: str | None) -> str | None:
  if raw is None:
    return None
  value = raw.strip()
  if value == "":
    return None
  return value


def _parse_optional_int(raw: str | None) -> int | None:
  if raw is None or raw.strip() == "":
    return None

  value = int(raw)

  if value <= 0:
    raise ValueError("Optional TTL seconds must be positive when provided.")

  return value
