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
    debug: bool
    max_topic_length: int
    job_max_retries: int
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
    jobs_auto_process: bool
    pg_dsn: str | None
    pg_connect_timeout: int
    pg_lessons_table: str
    pg_jobs_table: str
    llm_audit_enabled: bool
    cache_lesson_catalog: bool


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

    # Toggle verbose error output and diagnostics in non-production environments.
    debug = _parse_bool(os.getenv("DGS_DEBUG"))

    max_topic_length = int(os.getenv("DGS_MAX_TOPIC_LENGTH", "200"))

    if max_topic_length <= 0:
        raise ValueError("DGS_MAX_TOPIC_LENGTH must be a positive integer.")

    # Clamp retry attempts to avoid runaway costs on failed jobs.
    job_max_retries = int(os.getenv("DGS_JOB_MAX_RETRIES", "1"))

    if job_max_retries < 0:
        raise ValueError("DGS_JOB_MAX_RETRIES must be zero or a positive integer.")

    return Settings(
        dev_key=dev_key,
        allowed_origins=_parse_origins(os.getenv("DGS_ALLOWED_ORIGINS")),
        debug=debug,
        max_topic_length=max_topic_length,
        job_max_retries=job_max_retries,
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
        jobs_auto_process=_parse_bool(os.getenv("DGS_JOBS_AUTO_PROCESS")),
        pg_dsn=os.getenv("DGS_PG_DSN"),
        pg_connect_timeout=int(os.getenv("DGS_PG_CONNECT_TIMEOUT", "5")),
        pg_lessons_table=os.getenv("DGS_PG_LESSONS_TABLE", "dgs_lessons"),
        pg_jobs_table=os.getenv("DGS_PG_JOBS_TABLE", "dgs_jobs"),
        llm_audit_enabled=_parse_bool(os.getenv("DGS_LLM_AUDIT_ENABLED")),
        cache_lesson_catalog=_parse_bool(os.getenv("DGS_CACHE_LESSON_CATALOG")),
    )


def _parse_optional_int(raw: str | None) -> int | None:

    if raw is None or raw.strip() == "":
        return None

    value = int(raw)

    if value <= 0:
        raise ValueError("Optional TTL seconds must be positive when provided.")

    return value
