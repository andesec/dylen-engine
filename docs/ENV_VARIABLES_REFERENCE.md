h s# Environment Variables Quick Reference

## Updated: February 11, 2026

This is a quick reference for all environment variables after the refactoring.

## Required Variables

### Runtime Identity
- `DYLEN_ENV` - Runtime environment (development, stage, production)
- `DYLEN_ALLOWED_ORIGINS` - CORS allowed origins (comma-separated, no wildcards)

### Database
- `DYLEN_PG_DSN` - PostgreSQL connection string (required)
- `DATABASE_URL` - Alias for DYLEN_PG_DSN

### API Keys (Secrets)
- `GEMINI_API_KEY` - Google Gemini API key (required)
- `OPENROUTER_API_KEY` - OpenRouter API key (required)

### Firebase/GCP
- `GCP_PROJECT_ID` - GCP project ID (required)
- `GCP_LOCATION` - GCP region (required)
- `FIREBASE_PROJECT_ID` - Firebase project ID (required)
- `DYLEN_ILLUSTRATION_BUCKET` - GCS bucket for illustrations (required)

## Optional Variables

### AI Models (Combined Provider/Model Format)
```bash
# Format: provider/model-name
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

### Research Models
```bash
DYLEN_RESEARCH_MODEL=gemini/gemini-1.5-pro
DYLEN_RESEARCH_ROUTER_MODEL=gemini/gemini-1.5-flash
DYLEN_RESEARCH_SEARCH_MAX_RESULTS=5
```

### API Keys (Optional Features)
```bash
TAVILY_API_KEY=...  # Research/search functionality
DYLEN_MAILERSEND_API_KEY=...  # Email notifications
```

### Cloud Tasks (GCP)
```bash
DYLEN_TASK_SERVICE_PROVIDER=gcp  # or "local-http"
DYLEN_CLOUD_TASKS_QUEUE_PATH=projects/PROJECT/locations/REGION/queues/QUEUE
DYLEN_INTERNAL_SERVICE_URL=https://<cloud-run-service-url>  # Direct Cloud Run URL for task callbacks
DYLEN_BASE_URL=https://your-service.run.app
DYLEN_TASK_SECRET=...  # Secret for task authentication
DYLEN_CLOUD_RUN_INVOKER_SERVICE_ACCOUNT=...@....iam.gserviceaccount.com
```

### Email Notifications
```bash
DYLEN_EMAIL_NOTIFICATIONS_ENABLED=false
DYLEN_EMAIL_PROVIDER=mailersend
DYLEN_EMAIL_FROM_ADDRESS=no-reply@example.com
DYLEN_EMAIL_FROM_NAME=Dylen
DYLEN_MAILERSEND_TIMEOUT_SECONDS=10
DYLEN_MAILERSEND_BASE_URL=https://api.mailersend.com/v1
```

### Push Notifications
```bash
DYLEN_PUSH_NOTIFICATIONS_ENABLED=false
DYLEN_PUSH_VAPID_PUBLIC_KEY=...
DYLEN_PUSH_VAPID_PRIVATE_KEY=...
DYLEN_PUSH_VAPID_SUB=mailto:alerts@example.com
```

### Export/Import (Data Transfer)
```bash
DYLEN_EXPORT_BUCKET=...  # GCS bucket for exports
DYLEN_EXPORT_OBJECT_PREFIX=data-transfer
DYLEN_EXPORT_SIGNED_URL_TTL_SECONDS=900
DYLEN_EXPORT_MAX_ZIP_BYTES=...  # Optional size limit
```

### Database & Storage
```bash
DYLEN_PG_CONNECT_TIMEOUT=5
GCS_STORAGE_HOST=  # For local fake-gcs-server, leave empty in production
```

### Logging
```bash
DYLEN_LOG_MAX_BYTES=5242880  # 5MB default
DYLEN_LOG_BACKUP_COUNT=10
DYLEN_LOG_HTTP_4XX=false  # Log 4xx errors
DYLEN_LOG_HTTP_BODIES=false  # Log request/response bodies
DYLEN_LOG_HTTP_BODY_BYTES=2048
```

### Schema & Prompts
```bash
DYLEN_SCHEMA_VERSION=1.0
DYLEN_PROMPT_VERSION=v1
DYLEN_MAX_MARKDOWN_CHARS=1500
```

### Debug & Development
```bash
DYLEN_DEBUG=false
DYLEN_BACKUP_DIR=./backups
DYLEN_LLM_AUDIT_ENABLED=false
```

### Firebase Authentication
```bash
FIREBASE_SERVICE_ACCOUNT_JSON_PATH=/path/to/serviceAccountKey.json
# Note: In GCP, use Application Default Credentials instead
```

### OpenRouter Attribution (Optional)
```bash
OPENROUTER_HTTP_REFERER=https://your-app.example
OPENROUTER_TITLE=YourAppName
```

### Dev/Test: Dummy Responses
```bash
# Set to true to use fixture files instead of API calls
DYLEN_USE_DUMMY_PLANNER_RESPONSE=false
DYLEN_DUMMY_PLANNER_RESPONSE_PATH=./fixtures/dummy_planner_response.md
DYLEN_USE_DUMMY_OUTCOMES_RESPONSE=false
DYLEN_DUMMY_OUTCOMES_RESPONSE_PATH=./fixtures/dummy_outcomes_response.md
DYLEN_USE_DUMMY_SECTION_BUILDER_RESPONSE=false
DYLEN_DUMMY_SECTION_BUILDER_RESPONSE_PATH=./fixtures/dummy_section_builder_response.md
DYLEN_USE_DUMMY_REPAIRER_RESPONSE=false
DYLEN_DUMMY_REPAIRER_RESPONSE_PATH=./fixtures/dummy_repairer_response.md
```

### Deployment (Scripts Only - Not for .env)
```bash
# These are used by deployment scripts, not runtime
DEPLOY_PROJECT_ID=...
DEPLOY_REGION=...
DEPLOY_AR_REPO=...
DEPLOY_IMAGE=...
DEPLOY_SERVICE=...
DEPLOY_MIGRATE_JOB=...
DEPLOY_RUN_SA=...
DEPLOY_CLOUDSQL_INSTANCE=...
DEPLOY_DB_NAME=...
DEPLOY_DB_USER=...
DEPLOY_DB_PASSWORD_SECRET=...
DEPLOY_CLOUD_TASKS_QUEUE_NAME=...
DEPLOY_CLOUD_TASKS_INVOKER_SA=...
DEPLOY_TAG=...
DEPLOY_ILLUSTRATION_BUCKET=...
```

## Removed Variables (No Longer Supported)

These variables have been **removed** and should be deleted from all `.env` files:

```bash
# ❌ REMOVED - No longer used
DYLEN_APP_ID
DYLEN_MAX_TOPIC_LENGTH  # Now in runtime_config_values table
DYLEN_JOB_MAX_RETRIES  # No retries by default
DYLEN_JOBS_TTL_SECONDS  # No TTL by default
DYLEN_JOBS_AUTO_PROCESS  # Now in runtime_config_values table
DYLEN_CACHE_LESSON_CATALOG  # Now in runtime_config_values table
DYLEN_AUTO_APPLY_MIGRATIONS  # Manage via deployment scripts
DYLEN_PG_LESSONS_TABLE  # Hardcoded to "lessons"
DYLEN_PG_JOBS_TABLE  # Hardcoded to "jobs"

# ❌ REMOVED - Combined into *_MODEL variables
DYLEN_SECTION_BUILDER_PROVIDER
DYLEN_PLANNER_PROVIDER
DYLEN_OUTCOMES_PROVIDER
DYLEN_REPAIR_PROVIDER
DYLEN_FENSTER_PROVIDER
DYLEN_WRITING_PROVIDER
DYLEN_TUTOR_PROVIDER
DYLEN_ILLUSTRATION_PROVIDER
DYLEN_VISUALIZER_PROVIDER
DYLEN_YOUTUBE_PROVIDER
```

## Runtime-Configurable Settings (Database)

These settings are managed via the `runtime_config_values` table, not environment variables:

| Key | Default | Scope | Description |
|-----|---------|-------|-------------|
| `limits.max_topic_length` | 200 | TIER + TENANT | Max topic length for lessons |
| `jobs.auto_process` | true | GLOBAL + TENANT | Auto-process jobs on creation |
| `jobs.max_retries` | 0 | GLOBAL | Job retry attempts |
| `jobs.ttl_seconds` | null | GLOBAL | Job TTL in seconds |
| `lessons.cache_catalog` | false | GLOBAL | Enable lesson catalog caching |

See `docs/runtime_configuration_plan.md` for full runtime config documentation.

## Examples by Environment

### Development (.env)
```bash
DYLEN_ENV=development
DYLEN_ALLOWED_ORIGINS=http://localhost:3000
DYLEN_PG_DSN=postgresql://user:pass@localhost:5432/dylen_dev
GEMINI_API_KEY=your_dev_key
OPENROUTER_API_KEY=your_openrouter_key
GCP_PROJECT_ID=dylen-dev
GCP_LOCATION=us-central1
FIREBASE_PROJECT_ID=dylen-dev
DYLEN_ILLUSTRATION_BUCKET=dylen-dev-illustrations
DYLEN_DEBUG=true
```

### Stage (.env-stage)
```bash
DYLEN_ENV=stage
DYLEN_ALLOWED_ORIGINS=https://stage.dylen.app
DYLEN_PG_DSN=postgresql://...@/dylen-stage?host=/cloudsql/...
GEMINI_API_KEY=...
OPENROUTER_API_KEY=...
GCP_PROJECT_ID=dylen-stage-485900
GCP_LOCATION=us-central1
FIREBASE_PROJECT_ID=dylen-stage-485900
DYLEN_ILLUSTRATION_BUCKET=dylen-stage-illustrations
DYLEN_TASK_SERVICE_PROVIDER=gcp
DYLEN_CLOUD_TASKS_QUEUE_PATH=projects/dylen-stage-485900/locations/us-central1/queues/dylen-jobs-queue
DYLEN_BASE_URL=https://dylen-engine-stage-....run.app
DYLEN_EMAIL_NOTIFICATIONS_ENABLED=true
```

### Production (.env-prod)
```bash
DYLEN_ENV=production
DYLEN_ALLOWED_ORIGINS=https://app.dylen.app,https://dylen.app
DYLEN_PG_DSN=postgresql://...@/dylen-prod?host=/cloudsql/...
GEMINI_API_KEY=...
OPENROUTER_API_KEY=...
GCP_PROJECT_ID=dylen-prod
GCP_LOCATION=us-central1
FIREBASE_PROJECT_ID=dylen-prod
DYLEN_ILLUSTRATION_BUCKET=dylen-illustrations
DYLEN_TASK_SERVICE_PROVIDER=gcp
DYLEN_CLOUD_TASKS_QUEUE_PATH=projects/dylen-prod/locations/us-central1/queues/dylen-jobs-queue
DYLEN_BASE_URL=https://api.dylen.app
DYLEN_EMAIL_NOTIFICATIONS_ENABLED=true
DYLEN_PUSH_NOTIFICATIONS_ENABLED=true
```

