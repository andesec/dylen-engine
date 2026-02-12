# CHANGELOG - Environment Variables Refactoring

## [Unreleased] - 2026-02-11

### BREAKING CHANGES

#### Environment Variables Removed
The following environment variables have been **removed** and must be deleted from all `.env` files:

- `DYLEN_APP_ID` - No longer used
- `DYLEN_JOB_MAX_RETRIES` - Jobs no longer retry by default
- `DYLEN_MAX_TOPIC_LENGTH` - Now managed via runtime config (default: 200)
- `DYLEN_JOBS_TTL_SECONDS` - No TTL by default
- `DYLEN_JOBS_AUTO_PROCESS` - Now managed via runtime config (default: true)
- `DYLEN_CACHE_LESSON_CATALOG` - Now managed via runtime config (default: false)
- `DYLEN_AUTO_APPLY_MIGRATIONS` - Should be managed via deployment scripts
- `DYLEN_PG_LESSONS_TABLE` - Hardcoded to "lessons"
- `DYLEN_PG_JOBS_TABLE` - Hardcoded to "jobs"

#### AI Model Configuration Format Changed
All AI model configurations now use a **combined format**: `provider/model`

**Before:**
```bash
DYLEN_SECTION_BUILDER_PROVIDER=gemini
DYLEN_SECTION_BUILDER_MODEL=gemini-2.5-pro
```

**After:**
```bash
DYLEN_SECTION_BUILDER_MODEL=gemini/gemini-2.5-pro
```

**All provider variables removed:**
- `DYLEN_SECTION_BUILDER_PROVIDER`
- `DYLEN_PLANNER_PROVIDER`
- `DYLEN_OUTCOMES_PROVIDER`
- `DYLEN_REPAIR_PROVIDER`
- `DYLEN_FENSTER_PROVIDER`
- `DYLEN_WRITING_PROVIDER`
- `DYLEN_TUTOR_PROVIDER`
- `DYLEN_ILLUSTRATION_PROVIDER`
- `DYLEN_YOUTUBE_PROVIDER`

**New format examples:**
```bash
DYLEN_SECTION_BUILDER_MODEL=gemini/gemini-2.5-pro
DYLEN_PLANNER_MODEL=gemini/gemini-2.5-pro
DYLEN_OUTCOMES_MODEL=gemini/gemini-2.5-flash
DYLEN_REPAIR_MODEL=gemini/gemini-2.5-flash
DYLEN_FENSTER_MODEL=gemini/gemini-2.5-flash
DYLEN_WRITING_MODEL=gemini/gemini-2.5-flash
DYLEN_TUTOR_MODEL=gemini/gemini-2.5-flash
DYLEN_ILLUSTRATION_MODEL=gemini/gemini-2.5-flash-image
DYLEN_YOUTUBE_MODEL=gemini/gemini-2.0-flash
```

### Added

#### New Research Model Variables
Research functionality now has explicit model configuration:
```bash
DYLEN_RESEARCH_MODEL=gemini/gemini-1.5-pro
DYLEN_RESEARCH_ROUTER_MODEL=gemini/gemini-1.5-flash
DYLEN_RESEARCH_SEARCH_MAX_RESULTS=5
```

### Changed

#### Runtime Configuration Defaults
The following settings are now **runtime-configurable via database** and no longer in `.env`:

| Setting | Default | Scope | Notes |
|---------|---------|-------|-------|
| `limits.max_topic_length` | 200 | Tier + Tenant | Max characters for lesson topics |
| `jobs.auto_process` | true | Global + Tenant | Auto-process jobs on creation |
| `jobs.max_retries` | 0 | Global | No retries by default |
| `jobs.ttl_seconds` | null | Global | No TTL by default |
| `lessons.cache_catalog` | false | Global | Lesson catalog caching |

#### Database Table Names
- Lessons table: hardcoded to `"lessons"` (was configurable via `DYLEN_PG_LESSONS_TABLE`)
- Jobs table: hardcoded to `"jobs"` (was configurable via `DYLEN_PG_JOBS_TABLE`)

#### Job Processing
- Job TTL is now always `null` (no expiration)
- Job max retries is now `0` by default (no automatic retries)
- Auto-processing is fetched from runtime config per-tenant
- Admin-triggered jobs (retry, maintenance, data-transfer) always auto-process

### Migration Guide

#### 1. Update `.env` Files

**Remove these lines:**
```bash
DYLEN_APP_ID=...
DYLEN_MAX_TOPIC_LENGTH=...
DYLEN_JOB_MAX_RETRIES=...
DYLEN_JOBS_TTL_SECONDS=...
DYLEN_JOBS_AUTO_PROCESS=...
DYLEN_CACHE_LESSON_CATALOG=...
DYLEN_AUTO_APPLY_MIGRATIONS=...
DYLEN_PG_LESSONS_TABLE=...
DYLEN_PG_JOBS_TABLE=...

# All these provider lines:
DYLEN_SECTION_BUILDER_PROVIDER=...
DYLEN_PLANNER_PROVIDER=...
DYLEN_OUTCOMES_PROVIDER=...
DYLEN_REPAIR_PROVIDER=...
DYLEN_FENSTER_PROVIDER=...
DYLEN_WRITING_PROVIDER=...
DYLEN_TUTOR_PROVIDER=...
DYLEN_ILLUSTRATION_PROVIDER=...
DYLEN_YOUTUBE_PROVIDER=...
```

**Update these to combined format:**
```bash
# OLD:
DYLEN_SECTION_BUILDER_PROVIDER=gemini
DYLEN_SECTION_BUILDER_MODEL=gemini-2.5-pro

# NEW:
DYLEN_SECTION_BUILDER_MODEL=gemini/gemini-2.5-pro
```

**Add research model config (if using research features):**
```bash
DYLEN_RESEARCH_MODEL=gemini/gemini-1.5-pro
DYLEN_RESEARCH_ROUTER_MODEL=gemini/gemini-1.5-flash
DYLEN_RESEARCH_SEARCH_MAX_RESULTS=5
```

#### 2. Update Runtime Config Table

Ensure the `runtime_config_values` table has proper defaults seeded:

```sql
-- Global defaults
INSERT INTO runtime_config_values (id, key, scope, value_json)
VALUES 
  (gen_random_uuid(), 'jobs.auto_process', 'GLOBAL', 'true'),
  (gen_random_uuid(), 'jobs.max_retries', 'GLOBAL', '0'),
  (gen_random_uuid(), 'lessons.cache_catalog', 'GLOBAL', 'false')
ON CONFLICT DO NOTHING;
```

#### 3. Update Deployment Scripts

If you're using `DYLEN_AUTO_APPLY_MIGRATIONS`, update deployment scripts to handle migrations explicitly rather than via env var.

#### 4. Verify Configuration

After updating:
1. Check that AI agents still work with the combined provider/model format
2. Verify job creation and auto-processing works
3. Test quota enforcement
4. Test export/import functionality (if used)
5. Test research features (if used)

### No Backwards Compatibility

**Warning:** This is a breaking change with no backwards compatibility. All `.env` files must be updated immediately when deploying this version.

### Files Modified

- `.env.example`
- `.env-stage`
- `app/config.py`
- `app/core/env_contract.py`
- `app/services/runtime_config.py`
- `app/services/jobs.py`
- `app/services/request_validation.py`
- `app/ai/agents/research.py`
- `app/storage/factory.py`
- `app/api/routes/admin.py`
- `app/api/routes/data_transfer.py`
- `scripts/inspect_job.py`

### Documentation

- Added: `docs/env_audit_changes_summary.md` - Complete audit summary
- Update required: `docs/runtime_configuration_plan.md` - Reflect actual implementation
- Update required: `README.md` - Update environment setup instructions

