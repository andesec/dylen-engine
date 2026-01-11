"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from app.utils.env import default_env_path, load_env_file

load_env_file(default_env_path(), override=False)


@dataclass(frozen=True)
class Settings:
    """Typed settings for the DGS service."""

    dev_key: str
    allowed_origins: list[str]
    max_topic_length: int
    ddb_table: str
    jobs_table: str
    ddb_region: str
    ddb_endpoint_url: str | None
    gatherer_provider: str
    gatherer_model: str | None
    planner_provider: str
    planner_model: str | None
    structurer_provider: str
    structurer_model: str | None
    structurer_model_fast: str | None
    structurer_model_balanced: str | None
    structurer_model_best: str | None
    repair_provider: str
    repair_model: str | None
    prompt_version: str
    schema_version: str
    merge_gatherer_structurer: bool
    tenant_key: str
    lesson_id_index_name: str
    jobs_all_jobs_index_name: str | None
    jobs_idempotency_index_name: str | None
    jobs_ttl_seconds: int | None
    jobs_auto_process: bool
    pg_dsn: str | None
    pg_connect_timeout: int
    llm_audit_enabled: bool


def _parse_origins(raw: str | None) -> list[str]:

    if not raw:
        raise ValueError("DGS_ALLOWED_ORIGINS must be set to one or more origins.")

    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]

    if not origins:
        raise ValueError("DGS_ALLOWED_ORIGINS must include at least one origin.")

    if "*" in origins:
        raise ValueError("DGS_ALLOWED_ORIGINS must not include wildcard origins.")

    return origins


def _parse_bool(raw: str | None) -> bool:
    """Parse a boolean-ish string from environment variables."""

    if raw is None:
        return False

    normalized = raw.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process."""

    dev_key = os.getenv("DGS_DEV_KEY", "").strip()

    if not dev_key:
        raise ValueError("DGS_DEV_KEY must be set to a non-empty value.")

    max_topic_length = int(os.getenv("DGS_MAX_TOPIC_LENGTH", "200"))

    if max_topic_length <= 0:
        raise ValueError("DGS_MAX_TOPIC_LENGTH must be a positive integer.")

    return Settings(
        dev_key=dev_key,
        allowed_origins=_parse_origins(os.getenv("DGS_ALLOWED_ORIGINS")),
        max_topic_length=max_topic_length,
        ddb_table=os.getenv("DGS_DDB_TABLE", "Lessons"),
        jobs_table=os.getenv("DGS_JOBS_TABLE", "dgs_jobs"),
        ddb_region=os.getenv("AWS_REGION", "us-east-1"),
        ddb_endpoint_url=os.getenv("DGS_DDB_ENDPOINT_URL"),
        gatherer_provider=os.getenv("DGS_GATHERER_PROVIDER", "openrouter"),
        gatherer_model=os.getenv("DGS_GATHERER_MODEL", "xiaomi/mimo-v2-flash:free"),
        planner_provider=os.getenv("DGS_PLANNER_PROVIDER", os.getenv("DGS_STRUCTURER_PROVIDER", "openrouter")),
        planner_model=os.getenv("DGS_PLANNER_MODEL", "openai/gpt-oss-120b:free"),
        structurer_provider=os.getenv("DGS_STRUCTURER_PROVIDER", "openrouter"),
        structurer_model=os.getenv("DGS_STRUCTURER_MODEL", "openai/gpt-oss-20b:free"),
        structurer_model_fast=os.getenv("DGS_STRUCTURER_MODEL_FAST"),
        structurer_model_balanced=os.getenv("DGS_STRUCTURER_MODEL_BALANCED"),
        structurer_model_best=os.getenv("DGS_STRUCTURER_MODEL_BEST"),
        repair_provider=os.getenv(
            "DGS_REPAIR_PROVIDER", os.getenv("DGS_STRUCTURER_PROVIDER", "gemini")
        ),
        repair_model=os.getenv("DGS_REPAIR_MODEL", "google/gemma-3-27b-it:free"),
        prompt_version=os.getenv("DGS_PROMPT_VERSION", "v1"),
        schema_version=os.getenv("DGS_SCHEMA_VERSION", "1.0"),
        merge_gatherer_structurer=_parse_bool(os.getenv("MERGE_GATHERER_STRUCTURER")),
        tenant_key=os.getenv("DGS_TENANT_KEY", "TENANT#default"),
        lesson_id_index_name=os.getenv("DGS_LESSON_ID_INDEX", "lesson_id_index"),
        jobs_all_jobs_index_name=os.getenv("DGS_JOBS_ALL_JOBS_INDEX", "jobs_all_jobs"),
        jobs_idempotency_index_name=os.getenv("DGS_JOBS_IDEMPOTENCY_INDEX", "jobs_idempotency"),
        jobs_ttl_seconds=_parse_optional_int(os.getenv("DGS_JOBS_TTL_SECONDS")),
        jobs_auto_process=_parse_bool(os.getenv("DGS_JOBS_AUTO_PROCESS")),
        pg_dsn=os.getenv("DGS_PG_DSN"),
        pg_connect_timeout=int(os.getenv("DGS_PG_CONNECT_TIMEOUT", "5")),
        llm_audit_enabled=_parse_bool(os.getenv("DGS_LLM_AUDIT_ENABLED")),
    )


def _parse_optional_int(raw: str | None) -> int | None:

    if raw is None or raw.strip() == "":
        return None

    value = int(raw)

    if value <= 0:
        raise ValueError("Optional TTL seconds must be positive when provided.")

    return value
