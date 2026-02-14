# Stage Deployment A-to-Z (Run Now)

This runbook is the exact sequence to get Stage deployed and running now.

## A. Prerequisites (local machine)

1. Install and authenticate CLIs:
   - `gcloud` (with access to Stage project)
   - `gh` (if triggering GitHub workflow manually)
   - Docker (for Cloud Build source submission context)
2. Confirm repo root:
   - `cd /Users/nd/dev/andesec/dylen-engine`
3. Confirm auth/project:
   - `gcloud auth login`
   - `gcloud config set project dylen-stage-485900`

## B. Prepare `.env-stage` (local only, not committed)

Create/update `.env-stage` with at least the required keys:

- `DYLEN_ENV=stage`
- `DYLEN_ALLOWED_ORIGINS=https://stage.dylen.app`
- `DEPLOY_DB_NAME=dylen-stage`
- `DEPLOY_DB_USER=dylen-stage-user`
- `DEPLOY_DB_PASSWORD_SECRET=STAGE_DB_PASSWORD`
- `GCP_PROJECT_ID=dylen-stage-485900`
- `GCP_LOCATION=us-central1`
- `FIREBASE_PROJECT_ID=dylen-stage-485900`
- `DYLEN_ILLUSTRATION_BUCKET=dylen-stage-illustrations`
- `GEMINI_API_KEY=...`

## C. Sync `.env-stage` to Secret Manager

Dry-run first:

```bash
uv run python scripts/gcp_sync_env_to_secrets.py \
  --project-id dylen-stage-485900 \
  --env-file .env-stage \
  --target both \
  --default-dylen-env stage \
  --allow-unknown \
  --dry-run
```

Apply:

```bash
uv run python scripts/gcp_sync_env_to_secrets.py \
  --project-id dylen-stage-485900 \
  --env-file .env-stage \
  --target both \
  --default-dylen-env stage \
  --allow-unknown
```

Quick secret presence check:

```bash
for s in DYLEN_ENV DYLEN_ALLOWED_ORIGINS DYLEN_PG_DSN GCP_PROJECT_ID GCP_LOCATION FIREBASE_PROJECT_ID DYLEN_ILLUSTRATION_BUCKET GEMINI_API_KEY; do
  gcloud secrets describe "$s" --project dylen-stage-485900 >/dev/null && echo "OK $s" || echo "MISSING $s"
done
```

## D. Deploy Stage Right Now (local immediate path)

### Option 1 (recommended): single orchestrator script

```bash
scripts/deploy_stage_now.sh \
  --project-id dylen-stage-485900 \
  --region us-central1 \
  --ar-repo dylen-stage \
  --image app \
  --service dylen-engine-stage \
  --migrate-job dylen-engine-stage-migrate \
  --run-sa sa-dylen-stage@dylen-stage-485900.iam.gserviceaccount.com \
  --cloudsql-instance dylen-stage-485900:us-central1:dylen-stage-e \
  --db-name dylen-stage \
  --db-user dylen-stage-user \
  --db-password-secret STAGE_DB_PASSWORD \
  --env-file .env-stage \
  --org-id <YOUR_ORG_ID> \
  --environment-tag-short-name staging \
  --dylen-env stage \
  --allow-unknown-env \
  --skip-secrets-stage \
  --allowed-origins https://stage.dylen.app
```

Script path:
- `scripts/deploy_stage_now.sh`

What it performs:
1. Optional `gcloud auth login`.
2. `gcloud config set project`.
3. Ensures the GCP project has an `environment` tag binding.
4. Reads DB password from Secret Manager (`DEPLOY_DB_PASSWORD_SECRET`) and derives `DYLEN_PG_DSN`.
5. Persists deploy arguments into `.env-stage` (`DEPLOY_*` keys), writes `DYLEN_PG_DSN`, and updates `DYLEN_ENV` / optional `DYLEN_ALLOWED_ORIGINS`.
6. Directly updates `DYLEN_PG_DSN` secret (unless `--skip-dsn-secret-update` is used).
7. `.env-stage` validation + Secret Manager sync (unless `--skip-secrets-stage` or `--skip-env-sync` is used).
8. Required secret presence verification.
9. Optional `DYLEN_ALLOWED_ORIGINS` override.
10. `gcloud builds submit` using `cloudbuild-stage.migrate.yml`.
11. Service URL fetch + health check.
12. Revision/image + migration execution summary.

If your `.env-stage` includes keys outside the current runtime contract registry, keep `--allow-unknown-env`.
If secrets are already set and you want maximum speed, add `--skip-secrets-stage`.

### Option 2: manual commands

Run Cloud Build directly:

```bash
gcloud builds submit \
  --project dylen-stage-485900 \
  --config cloudbuild-stage.migrate.yml \
  --substitutions "_REGION=us-central1,_AR_REPO=dylen-stage,_IMAGE=app,_TAG=$(git rev-parse --short=12 HEAD),_SERVICE=dylen-engine-stage,_MIGRATE_JOB=dylen-engine-stage-migrate,_RUN_SA=sa-dylen-stage@dylen-stage-485900.iam.gserviceaccount.com,_CLOUDSQL_INSTANCE=dylen-stage-485900:us-central1:dylen-stage-e"
```

What this does:
1. Validates required secrets exist.
2. Builds and pushes image.
3. Resolves image digest and tags `stage-current`.
4. Runs migration Cloud Run Job with that digest.
5. Deploys Cloud Run service pinned to that digest.

## E. Verify Stage is Running

Get URL:

```bash
STAGE_URL="$(gcloud run services describe dylen-engine-stage --region us-central1 --format='value(status.url)')"
echo "$STAGE_URL"
```

Health check:

```bash
curl -fsS "$STAGE_URL/health"
```

Check latest revision and image digest:

```bash
gcloud run services describe dylen-engine-stage \
  --region us-central1 \
  --format='yaml(status.latestReadyRevisionName,spec.template.spec.containers[0].image)'
```

Check migration job last execution:

```bash
gcloud run jobs executions list \
  --job dylen-engine-stage-migrate \
  --region us-central1 \
  --limit 3
```

## F. GitHub Automated Path (after local success)

If using GitHub Actions orchestration (`.github/workflows/deploy-stage.yml`), set these repository secrets:

- `GCP_STAGE_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_STAGE_SERVICE_ACCOUNT`
- `GCP_STAGE_PROJECT_ID`
- `GCP_STAGE_REGION`
- `GCP_STAGE_AR_REPO`
- `GCP_STAGE_IMAGE_NAME`
- `GCP_STAGE_SERVICE`
- `GCP_STAGE_MIGRATE_JOB`
- `GCP_STAGE_RUN_SERVICE_ACCOUNT`
- `GCP_STAGE_CLOUD_SQL_INSTANCE`

Manual trigger:

```bash
gh workflow run deploy-stage.yml
```

## G. Rollback (if needed)

List recent stage image digests:

```bash
gcloud artifacts docker images list us-central1-docker.pkg.dev/dylen-stage-485900/dylen-stage/app --include-tags
```

Deploy previous known-good digest:

```bash
gcloud run deploy dylen-engine-stage \
  --region us-central1 \
  --image "us-central1-docker.pkg.dev/dylen-stage-485900/dylen-stage/app@sha256:<KNOWN_GOOD_DIGEST>" \
  --service-account "sa-dylen-stage@dylen-stage-485900.iam.gserviceaccount.com" \
  --set-env-vars "DYLEN_AUTO_APPLY_MIGRATIONS=0,DYLEN_ENV_CONTRACT_ENFORCE=1,DYLEN_EMAIL_NOTIFICATIONS_ENABLED=0" \
  --set-cloudsql-instances "dylen-stage-485900:us-central1:dylen-stage-e" \
  --set-secrets "DYLEN_ENV=DYLEN_ENV:latest,DYLEN_ALLOWED_ORIGINS=DYLEN_ALLOWED_ORIGINS:latest,DYLEN_PG_DSN=DYLEN_PG_DSN:latest,DATABASE_URL=DYLEN_PG_DSN:latest,GCP_PROJECT_ID=GCP_PROJECT_ID:latest,GCP_LOCATION=GCP_LOCATION:latest,FIREBASE_PROJECT_ID=FIREBASE_PROJECT_ID:latest,DYLEN_ILLUSTRATION_BUCKET=DYLEN_ILLUSTRATION_BUCKET:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest" \
  --port 8002 \
  --allow-unauthenticated
```

## H. Known Operational Guardrails

- Runtime migrations are disabled on service (`DYLEN_AUTO_APPLY_MIGRATIONS=0`).
- Migrations run only in Cloud Run Job per deploy.
- Service startup enforces env contract and fails fast on missing required keys.
- Non-secret env values are logged at startup; secret values are always redacted.
