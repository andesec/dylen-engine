# Environment Variables Audit - Changes Summary

## Date: February 11, 2026

This document summarizes all changes made during the systematic environment variable audit and refactoring.

## Variables Removed from .env Files

### Completely Removed (Unused)
- `DYLEN_APP_ID` - Not meaningfully used, hardcoded to "dylen" where needed
- `DYLEN_JOB_MAX_RETRIES` - No retries by default (per user requirement)
- `DYLEN_MAX_TOPIC_LENGTH` - Moved to runtime config only (200 default)
- `DYLEN_JOBS_TTL_SECONDS` - No TTL by default
- `DYLEN_JOBS_AUTO_PROCESS` - Moved to runtime config (default: true)
- `DYLEN_CACHE_LESSON_CATALOG` - Moved to runtime config (default: false)
- `DYLEN_AUTO_APPLY_MIGRATIONS` - Deployment-phase only, should be managed via deployment scripts
- `DYLEN_PG_LESSONS_TABLE` - Hardcoded to "lessons"
- `DYLEN_PG_JOBS_TABLE` - Hardcoded to "jobs"

### Provider Variables Combined
All separate `*_PROVIDER` and `*_MODEL` variables were combined into a single `*_MODEL` variable using the format `provider/model`:

**Removed:**
- `DYLEN_SECTION_BUILDER_PROVIDER`, `DYLEN_PLANNER_PROVIDER`, `DYLEN_OUTCOMES_PROVIDER`
- `DYLEN_REPAIR_PROVIDER`, `DYLEN_FENSTER_PROVIDER`, `DYLEN_WRITING_PROVIDER`
- `DYLEN_TUTOR_PROVIDER`, `DYLEN_ILLUSTRATION_PROVIDER`, `DYLEN_YOUTUBE_PROVIDER`

**Kept (with new format):**
- `DYLEN_SECTION_BUILDER_MODEL=gemini/gemini-2.5-pro`
- `DYLEN_PLANNER_MODEL=gemini/gemini-2.5-pro`
- `DYLEN_OUTCOMES_MODEL=gemini/gemini-2.5-flash`
- `DYLEN_REPAIR_MODEL=gemini/gemini-2.5-flash`
- `DYLEN_FENSTER_MODEL=gemini/gemini-2.5-flash`
- `DYLEN_WRITING_MODEL=gemini/gemini-2.5-flash`
- `DYLEN_TUTOR_MODEL=gemini/gemini-2.5-flash`
- `DYLEN_ILLUSTRATION_MODEL=gemini/gemini-2.5-flash-image`
- `DYLEN_YOUTUBE_MODEL=gemini/gemini-2.0-flash`

**Research variables kept (actually used in code):**
- `DYLEN_RESEARCH_MODEL=gemini/gemini-1.5-pro`
- `DYLEN_RESEARCH_ROUTER_MODEL=gemini/gemini-1.5-flash`
- `DYLEN_RESEARCH_SEARCH_MAX_RESULTS=5`

## Variables Kept as Secrets/Infrastructure

These remain in `.env` files as they are secrets, deployment identifiers, or dev-only toggles:

### API Keys
- `GEMINI_API_KEY`
- `OPENROUTER_API_KEY`
- `TAVILY_API_KEY`
- `DYLEN_MAILERSEND_API_KEY`
- `DYLEN_PUSH_VAPID_PRIVATE_KEY`

### Database Connection
- `DYLEN_PG_DSN`
- `DATABASE_URL`
- `DYLEN_PG_CONNECT_TIMEOUT`

### Deployment Identifiers
- `GCP_PROJECT_ID`
- `GCP_LOCATION`
- `FIREBASE_PROJECT_ID`
- `FIREBASE_SERVICE_ACCOUNT_JSON_PATH`

### Dev-Only Toggles
- `DYLEN_USE_DUMMY_*`
- `DYLEN_DUMMY_*_PATH`
- `DYLEN_DEBUG`

### Security Boundaries
- `DYLEN_ALLOWED_ORIGINS`
- `OPENROUTER_HTTP_REFERER`
- `DYLEN_TASK_SECRET`

### Export/Import (Actually Used)
- `DYLEN_EXPORT_BUCKET`
- `DYLEN_EXPORT_OBJECT_PREFIX`
- `DYLEN_EXPORT_SIGNED_URL_TTL_SECONDS`
- `DYLEN_EXPORT_MAX_ZIP_BYTES`

### Cloud Tasks (GCP)
- `DYLEN_CLOUD_TASKS_QUEUE_PATH`
- `DYLEN_BASE_URL`
- `DYLEN_TASK_SERVICE_PROVIDER`
- `DYLEN_CLOUD_RUN_INVOKER_SERVICE_ACCOUNT`

## Code Changes

### app/config.py
- Removed fields from `Settings` dataclass: `app_id`, `max_topic_length`, `job_max_retries`, `jobs_ttl_seconds`, `jobs_auto_process`, `cache_lesson_catalog`
- Removed fields from `DatabaseSettings` dataclass: `pg_lessons_table`, `pg_jobs_table`
- Added `_parse_model_config()` helper function to parse combined provider/model format
- Updated `get_settings()` to use `_parse_model_config()` for all AI model variables
- Removed `_compute_job_ttl()` function

### app/core/env_contract.py
- Removed all unused environment variable definitions
- Removed all separate `*_PROVIDER` variable definitions
- Updated to reflect combined model format

### app/services/runtime_config.py
- Updated `_env_fallback()` to:
  - Return hardcoded `200` for `limits.max_topic_length`
  - Return `True` for `jobs.auto_process` (default enabled)
  - Return `None` for `jobs.ttl_seconds` (no TTL by default)
  - Return `0` for `jobs.max_retries` (no retries by default)
  - Return `False` for `lessons.cache_catalog` (runtime configurable)

### app/services/jobs.py
- Removed `_compute_job_ttl()` function
- Updated `trigger_job_processing()` to accept `auto_process` parameter
- Updated `create_job()` to:
  - Fetch `jobs.auto_process` from runtime config
  - Pass `auto_process` to `trigger_job_processing()`
  - Set `ttl=None` instead of computing from settings
- Updated `retry_job()` to pass `auto_process=True` (admin retries always process)

### app/services/request_validation.py
- Changed `_validate_generate_request()` to use hardcoded default `200` instead of `settings.max_topic_length`

### app/ai/agents/research.py
- Replaced `settings.app_id` with hardcoded `"dylen"`

### app/storage/factory.py
- Changed table names from `settings.pg_lessons_table` to hardcoded `"lessons"`
- Changed table names from `settings.pg_jobs_table` to hardcoded `"jobs"`

### app/api/routes/admin.py
- Updated maintenance job creation to pass `auto_process=True`

### app/api/routes/data_transfer.py
- Updated data transfer job creation to pass `auto_process=True`

### scripts/inspect_job.py
- Changed to use hardcoded `"jobs"` table name

## Environment File Updates

### .env.example
- Updated all AI model variables to combined format
- Removed unused variables
- Added research model variables

### .env-stage
- Updated all AI model variables to combined format
- Removed unused variables

## Runtime Configuration

The following settings are now exclusively managed via the `runtime_config_values` table:

- `limits.max_topic_length` - Default: 200 (Tier + Tenant override)
- `jobs.auto_process` - Default: true (Global + Tenant override)
- `jobs.max_retries` - Default: 0 (Global only)
- `jobs.ttl_seconds` - Default: None (Global only)
- `lessons.cache_catalog` - Default: false (Global only)

## Backwards Compatibility

**No backwards compatibility provided** - per user requirement, changes are immediate with clear CHANGELOG entry needed.

## Migration Notes

1. All existing `.env` files need to be updated to the new format
2. Runtime config table should be seeded with appropriate defaults
3. Deployment scripts may need updates to handle the removed `DYLEN_AUTO_APPLY_MIGRATIONS`

## Testing Checklist

- [ ] Verify all AI agents still work with combined provider/model format
- [ ] Verify job creation and processing works with runtime config
- [ ] Verify quota checks still work without max_topic_length in settings
- [ ] Verify export/import functionality still works
- [ ] Verify research agent works with new model configuration
- [ ] Run full integration test suite

