# Migration Process and Instructions

This document concisely describes the migration process implemented in this repo, with practical steps for development and production.

## Key Rules

- **One migration per PR** when schema files change (`dgs-backend/app/schema/`).
- **Single Alembic head** on `main` at all times.
- **No auto-migrations at app startup**; migrations run in a dedicated deploy step.
- **Autogenerate is a starting point only**; always review and edit migrations.
- **Reference/static data must be seeded via migrations**, not request-path code (idempotent, insert-missing).

## Directory Layout

- Alembic config: `dgs-backend/alembic.ini`
- Alembic env: `dgs-backend/alembic/env.py`
- Migrations: `dgs-backend/alembic/versions/`
- CI helpers: `scripts/`

## Create a Migration (Dev)

Do this one thing after you change models in `dgs-backend/app/schema/`:
```bash
make migration-auto m="short_description"
```
Prereqs:
- set `DGS_PG_DSN` and `DGS_ALLOWED_ORIGINS` in `.env` (or export them in your shell)

What it does (local dev only):
- ensures Postgres is running
- upgrades your local DB to `head`
- autogenerates a new revision
- runs lint + single-head check
- applies the new migration and runs drift detection

Then commit the generated migration file. If it contains unsafe ops, edit it before committing.

## Optional: Auto-Squash / Auto-Generate On Commit (Local Git Hook)

If you want commits to “just work” when you stage schema changes:
1) Install the repo hooks once:
```bash
make hooks-install
```
2) Optional env toggles:
- `DGS_AUTO_MIGRATIONS=1` auto-generates or auto-squashes migrations during `git commit`
- `MIGRATION_BASE_REF=release/1.2` changes the base branch used for squashing
- `SKIP_GIT_MIGRATION_HOOK=1` bypasses the hook
- `DGS_MIGRATION_HOOK_STRICT=1` also runs drift detection (slower; requires DB connectivity)

## Squash Multiple Local Migrations (Before Opening a PR)

If you created multiple migrations locally while iterating on a branch, squash them into one migration before you open the PR:
```bash
make migration-squash m="final_schema_changes"
```
This moves your extra local migration files into `dgs-backend/alembic/versions/.squash_backup/` and generates one new migration that represents the full diff from the PR base to your current models.
By default it computes the PR base using `git merge-base` against `origin/main`. If your PR targets another branch, set `MIGRATION_BASE_REF`:
```bash
make migration-squash m="final_schema_changes" MIGRATION_BASE_REF="release/1.2"
```
Make sure you have a recent `git fetch` for that branch.

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

## Adding New Seed / Static Data (Future Changes)

When you need new required reference rows (tiers/roles/permissions/feature flags), add them via an **idempotent Alembic migration**:
1) Generate a migration:
```bash
make migration-auto m="seed_<thing>"
```
2) Edit the migration to be safe to re-run:
- Prefer Postgres `INSERT .. ON CONFLICT DO NOTHING` (insert-missing) or `ON CONFLICT DO UPDATE` (managed seed data).
- Avoid deletes on downgrade; keep `downgrade()` a no-op for seed migrations.
3) If the application requires the data to exist to avoid 500s, extend `scripts/db_check_seed_data.py` and run:
```bash
make db-check-seed-data
```

### Static data missing (e.g. subscription tiers)
- Run migrations to apply seed-data migrations:
  ```bash
  make migrate
  ```
- Verify required reference rows exist:
  ```bash
  make db-check-seed-data
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
- Seed-data check (required reference rows like `subscription_tiers`):
  ```bash
  make db-check-seed-data
  ```

You can allowlist known-safe drift diffs by setting `DGS_MIGRATION_DRIFT_ALLOWLIST="token1,token2"` before running drift checks.
