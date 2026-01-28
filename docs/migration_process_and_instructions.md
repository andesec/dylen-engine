# Migration Process and Instructions

This document concisely describes the migration process implemented in this repo, with practical steps for development and production.

## Key Rules

- **One migration per PR** when schema files change (`dgs-backend/app/schema/`).
- **Single Alembic head** on `main` at all times.
- **No auto-migrations at app startup**; migrations run in a dedicated deploy step.
- **Autogenerate is a starting point only**; always review and edit migrations.

## Directory Layout

- Alembic config: `dgs-backend/alembic.ini`
- Alembic env: `dgs-backend/alembic/env.py`
- Migrations: `dgs-backend/alembic/versions/`
- CI helpers: `scripts/`

## Create a Migration (Dev)

1. Ensure the local DB is at head:
   ```bash
   make migrate
   ```
2. Change models in `dgs-backend/app/schema/`.
3. Generate a migration skeleton:
   ```bash
   make migration m="short_description"
   ```
4. **Edit the migration** for ordering, safety, backfills, and indexes.
5. Apply migrations:
   ```bash
   make migrate
   ```
6. Commit the migration file.

### Lint Tags (when needed)

- `# destructive: approved` — required for `drop_table` / `drop_column` in `upgrade()`
- `# empty: allow` — allow empty merge revisions
- `# backfill: ok` — acknowledges backfill for `nullable=False` changes
- `# type-change: approved` — required for type changes in `upgrade()`

## Run Migrations in Development

- Using make:
  ```bash
  make migrate
  ```
- Or directly with Alembic:
  ```bash
  cd dgs-backend
  uv run alembic upgrade head
  ```

## Run Migrations in Production

1. **Staging first** (required):
   ```bash
   cd dgs-backend
   DGS_PG_DSN=postgresql://... DGS_ALLOWED_ORIGINS=https://your-app.example uv run alembic upgrade head
   ```
2. Validate staging health checks.
3. **Production deploy step**:
   ```bash
   cd dgs-backend
   DGS_PG_DSN=postgresql://... DGS_ALLOWED_ORIGINS=https://your-app.example uv run alembic upgrade head
   ```

> If you ever auto-run migrations at startup, enforce a single migration lock (e.g., Postgres advisory lock) to prevent concurrent runs.

## Fixing Migration Failures

### Fixing a migration script
- **Not merged / not applied anywhere shared:** edit the migration file, rerun `make migrate`, and update tags or backfills as needed.
- **Already applied in staging/production:** do **not** edit the applied revision; create a new corrective migration:
  ```bash
  make migration m="fix_<issue>"
  make migrate
  ```

### CI drift detected
- Generate and commit the missing migration:
  ```bash
  make migration m="fix_schema_drift"
  make migrate
  ```

### Multiple heads detected
- Rebase migrations or create a merge revision only when approved.

### Lint failures
- Add backfills for `nullable=False`, or apply `# backfill: ok` with a documented plan.
- Add `# destructive: approved` for drop operations after review.
- Add `# type-change: approved` and use expand/contract for type changes.

### Downgrade issues
- Downgrades are optional; document exceptions for lossy migrations and prefer forward fixes.

## Useful Checks

- Lint migrations:
  ```bash
  make db-migration-lint
  ```
- Single-head check:
  ```bash
  make db-heads
  ```
- Smoke test migrations (fresh + upgrade-from-previous):
  ```bash
  make db-migration-smoke
  ```
- Drift detection:
  ```bash
  make db-check-drift
  ```

You can allowlist known-safe drift diffs by setting `DGS_MIGRATION_DRIFT_ALLOWLIST="token1,token2"` before running drift checks.
