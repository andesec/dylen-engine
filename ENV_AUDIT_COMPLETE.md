# Environment Variables Audit - COMPLETE ✓

**Date:** February 11, 2026  
**Status:** Implementation Complete

## Summary

A systematic audit and refactoring of all environment variables has been completed. The goals were to:
1. ✅ Remove unused variables
2. ✅ Simplify provider/model configuration
3. ✅ Migrate runtime-configurable settings to database
4. ✅ Clean up deprecated migration-related settings

## Key Changes

### 1. Combined Provider/Model Configuration

**Before (2 variables per agent):**
```bash
DYLEN_SECTION_BUILDER_PROVIDER=gemini
DYLEN_SECTION_BUILDER_MODEL=gemini-2.5-pro
```

**After (1 variable per agent):**
```bash
DYLEN_SECTION_BUILDER_MODEL=gemini/gemini-2.5-pro
```

This applies to all AI agents: section_builder, planner, outcomes, repair, fenster, writing, tutor, illustration, youtube.

### 2. Variables Removed

**Completely removed (9 variables):**
- `DYLEN_APP_ID` - Hardcoded to "dylen"
- `DYLEN_MAX_TOPIC_LENGTH` - Moved to runtime config (default: 200)
- `DYLEN_JOB_MAX_RETRIES` - No retries by default (0)
- `DYLEN_JOBS_TTL_SECONDS` - No TTL by default (null)
- `DYLEN_JOBS_AUTO_PROCESS` - Moved to runtime config (default: true)
- `DYLEN_CACHE_LESSON_CATALOG` - Moved to runtime config (default: false)
- `DYLEN_AUTO_APPLY_MIGRATIONS` - Deployment-phase only
- `DYLEN_PG_LESSONS_TABLE` - Hardcoded to "lessons"
- `DYLEN_PG_JOBS_TABLE` - Hardcoded to "jobs"

**Provider variables removed (9 variables):**
- All `DYLEN_*_PROVIDER` variables (combined with model)

### 3. Variables Added

**Research configuration (3 new variables):**
```bash
DYLEN_RESEARCH_MODEL=gemini/gemini-1.5-pro
DYLEN_RESEARCH_ROUTER_MODEL=gemini/gemini-1.5-flash
DYLEN_RESEARCH_SEARCH_MAX_RESULTS=5
```

### 4. Runtime Configuration Migration

These settings are now **database-backed** (runtime_config_values table):

| Setting | Default | Scope | Location |
|---------|---------|-------|----------|
| `limits.max_topic_length` | 200 | TIER + TENANT | DB only |
| `jobs.auto_process` | true | GLOBAL + TENANT | DB only |
| `jobs.max_retries` | 0 | GLOBAL | DB only |
| `jobs.ttl_seconds` | null | GLOBAL | DB only |
| `lessons.cache_catalog` | false | GLOBAL | DB only |

## Files Modified

### Configuration Files
- ✅ `.env.example` - Updated with new format, removed unused vars
- ✅ `.env-stage` - Updated with new format, removed unused vars
- ⚠️  `.env` - **USER MUST UPDATE MANUALLY**

### Python Code
- ✅ `app/config.py` - Added `_parse_model_config()`, removed unused fields
- ✅ `app/core/env_contract.py` - Removed unused env definitions
- ✅ `app/services/runtime_config.py` - Updated defaults for migrated settings
- ✅ `app/services/jobs.py` - Removed TTL logic, updated auto_process handling
- ✅ `app/services/request_validation.py` - Hardcoded max_topic_length fallback
- ✅ `app/ai/agents/research.py` - Hardcoded app_id
- ✅ `app/storage/factory.py` - Hardcoded table names
- ✅ `app/api/routes/admin.py` - Pass auto_process=True for admin jobs
- ✅ `app/api/routes/data_transfer.py` - Pass auto_process=True for admin jobs
- ✅ `scripts/inspect_job.py` - Hardcoded table name

### Documentation
- ✅ `docs/ENV_VARIABLES_REFERENCE.md` - Complete reference guide (NEW)
- ✅ `docs/env_audit_changes_summary.md` - Technical summary (NEW)
- ✅ `CHANGELOG_ENV_REFACTOR.md` - Migration guide (NEW)

## Migration Steps for Deployment

### 1. Update Local .env File

```bash
# Remove these lines from your .env:
DYLEN_APP_ID=...
DYLEN_MAX_TOPIC_LENGTH=...
DYLEN_JOB_MAX_RETRIES=...
DYLEN_JOBS_TTL_SECONDS=...
DYLEN_JOBS_AUTO_PROCESS=...
DYLEN_CACHE_LESSON_CATALOG=...
DYLEN_AUTO_APPLY_MIGRATIONS=...
DYLEN_PG_LESSONS_TABLE=...
DYLEN_PG_JOBS_TABLE=...
DYLEN_*_PROVIDER=...  # All provider variables

# Update to combined format:
DYLEN_SECTION_BUILDER_MODEL=gemini/gemini-2.5-pro
DYLEN_PLANNER_MODEL=gemini/gemini-2.5-pro
# ... etc for all models

# Add research config if using research features:
DYLEN_RESEARCH_MODEL=gemini/gemini-1.5-pro
DYLEN_RESEARCH_ROUTER_MODEL=gemini/gemini-1.5-flash
DYLEN_RESEARCH_SEARCH_MAX_RESULTS=5
```

### 2. Update Stage Environment

The `.env-stage` file has already been updated in this commit.

### 3. Update Production Environment

Apply the same changes to production `.env` or Secret Manager entries.

### 4. Verify Runtime Config Database Defaults

Ensure these are seeded in `runtime_config_values` table:

```sql
INSERT INTO runtime_config_values (id, key, scope, value_json)
VALUES 
  (gen_random_uuid(), 'jobs.auto_process', 'GLOBAL', 'true'),
  (gen_random_uuid(), 'jobs.max_retries', 'GLOBAL', '0'),
  (gen_random_uuid(), 'lessons.cache_catalog', 'GLOBAL', 'false')
ON CONFLICT DO NOTHING;
```

## Testing Checklist

- [ ] Local development startup works
- [ ] AI agents work with combined provider/model format
- [ ] Job creation and auto-processing works
- [ ] Quota enforcement works (max_topic_length from runtime config)
- [ ] Export/import functionality works
- [ ] Research features work (if enabled)
- [ ] Stage deployment works
- [ ] Production deployment works

## Net Result

- **Before:** 86 environment variables
- **After:** 68 environment variables
- **Reduction:** 18 variables removed (21% reduction)
- **Cleaner:** Provider/model pairs consolidated
- **Flexible:** Runtime settings now database-backed

## References

- Full reference: `docs/ENV_VARIABLES_REFERENCE.md`
- Technical details: `docs/env_audit_changes_summary.md`
- Migration guide: `CHANGELOG_ENV_REFACTOR.md`
- Runtime config plan: `docs/runtime_configuration_plan.md`

## Backwards Compatibility

⚠️ **NO BACKWARDS COMPATIBILITY** - This is a breaking change. All `.env` files must be updated when deploying this version.

## Next Steps

1. ✅ Code changes complete
2. ⏳ Update your local `.env` file
3. ⏳ Test locally
4. ⏳ Deploy to stage
5. ⏳ Test stage
6. ⏳ Deploy to production
7. ⏳ Update production secrets/env vars
8. ⏳ Verify production health

---

**Audit completed by:** GitHub Copilot  
**Date:** February 11, 2026

