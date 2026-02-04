# Migration Process and Instructions

This document concisely describes the migration process implemented in this repo, with practical steps for development and production.

## Key Rules

- **Linear history only**: no Alembic merge revisions; maintain a single chain.
- **Order by Create Date** when multiple branches add migrations; edit `down_revision` to match the timestamp order.
- **Single Alembic head** on `main` at all times.
- **No auto-migrations at app startup**; migrations run in a dedicated deploy step.
- **Autogenerate is a starting point only**; always review and edit migrations.
- **Reference/static data must be seeded via seed scripts**, not request-path code (idempotent, insert-missing).
- **Handle Enums Idempotently**: When manually creating Enums (e.g., via `DO $$` blocks), set `create_type=False` in the SQLAlchemy Enum definition to avoid `DuplicateObjectError`.

## Directory Layout

- Alembic config: `dylen-engine/alembic.ini`
- Alembic env: `dylen-engine/alembic/env.py`
- Migrations: `dylen-engine/alembic/versions/`
- CI helpers: `scripts/`

## Create a Migration (Dev)

Do this after you change models in `dylen-engine/app/schema/`:
```bash
make migration-auto m="short_description"
```
Prereqs:
- set `DYLEN_PG_DSN` and `DYLEN_ALLOWED_ORIGINS` in `.env` (or export them in your shell)

What it does (local dev only):
- ensures Postgres is running
- upgrades your local DB to `head`
- autogenerates a new revision
- runs lint + single-head check
- applies the new migration and runs drift detection

Then commit the generated migration file. If it contains unsafe ops, edit it before committing.

After generating a migration, add a matching seed script when static data is required:
```bash
scripts/seeds/<revision_id>.py
```
Seed scripts run after migrations via `make seed` or `make migrate-and-seed`.

## Optional: Auto-Generate On Commit (Local Git Hook)

If you want commits to “just work” when you stage schema changes:
1) Install the repo hooks once:
```bash
make hooks-install
```
2) Optional env toggles:
- `DYLEN_AUTO_MIGRATIONS=1` auto-generates migrations during `git commit`
- `MIGRATION_BASE_REF=release/1.2` changes the base branch used for optional squashing
- `SKIP_GIT_MIGRATION_HOOK=1` bypasses the hook
- `DYLEN_MIGRATION_HOOK_STRICT=1` also runs drift detection (slower; requires DB connectivity)

## Optional: Squash Multiple Local Migrations

If you want a single migration before opening a PR, you can squash locally:
```bash
make migration-squash m="final_schema_changes"
```
This moves your extra migration files into `dylen-engine/alembic/versions/.squash_backup/` and generates one new migration that represents the full diff from the PR base to your current models.

### Lint Tags (when needed)

- `# destructive: approved` — required for `drop_table` / `drop_column` in `upgrade()`
- `# empty: allow` — allow empty migrations (merge revisions are not allowed)
- `# backfill: ok` — acknowledges backfill for `nullable=False` changes
- `# type-change: approved` — required for type changes in `upgrade()`

## Run Migrations in Development

- Using make:
  ```bash
  make migrate-and-seed
  ```
- Or directly with Alembic:
  ```bash
  cd dylen-engine
  uv run alembic upgrade head
  ```

## Reset Local DB + Recreate Baseline (Dev Only, Destructive)

If your local DB/migrations get into a broken state and you want to treat the database as brand new, you can nuke the local Postgres volume, delete all Alembic versions, and regenerate a fresh baseline from the current models:
```bash
make db-nuke CONFIRM_DB_NUKE=1
```
Notes:
- This deletes your local Docker Postgres volume (`docker-compose down -v`), so you will lose all local data.
- Do not run this against staging/production.

## Run Migrations in Production

1. **Staging first** (required):
   ```bash
   cd dylen-engine
   DYLEN_PG_DSN=postgresql://... DYLEN_ALLOWED_ORIGINS=https://your-app.example uv run alembic upgrade head
   DYLEN_PG_DSN=postgresql://... DYLEN_ALLOWED_ORIGINS=https://your-app.example uv run python scripts/run_seed_scripts.py
   ```
2. Validate staging health checks.
3. **Production deploy step**:
   ```bash
   cd dylen-engine
   DYLEN_PG_DSN=postgresql://... DYLEN_ALLOWED_ORIGINS=https://your-app.example uv run alembic upgrade head
   DYLEN_PG_DSN=postgresql://... DYLEN_ALLOWED_ORIGINS=https://your-app.example uv run python scripts/run_seed_scripts.py
   ```

> If you ever auto-run migrations at startup, enforce a single migration lock (e.g., Postgres advisory lock) to prevent concurrent runs.

## Fixing Migration Failures

### Fixing a migration script
- **Not merged / not applied anywhere shared:** edit the migration file, rerun `make migrate-and-seed`, and update tags or backfills as needed.
- **Already applied in staging/production:** do **not** edit the applied revision; create a new corrective migration:
  ```bash
  make migration m="fix_<issue>"
  make migrate-and-seed
  ```

## Adding New Seed / Static Data (Future Changes)

When you need new required reference rows (tiers/roles/permissions/feature flags), add them via an **idempotent seed script**:
1) Generate a migration:
```bash
make migration-auto m="add_<thing>"
```
2) Add a seed script with the same revision id:
```bash
scripts/seeds/<revision_id>.py
```
3) Use idempotent inserts (`ON CONFLICT DO NOTHING` or `DO UPDATE`) and guard with table/column checks.
4) If the application requires the data to exist to avoid 500s, extend `scripts/db_check_seed_data.py` and run:
```bash
make db-check-seed-data
```

### Static data missing (e.g. subscription tiers)
- Run migrations and seed scripts:
  ```bash
  make migrate-and-seed
  ```
- Verify required reference rows exist:
  ```bash
  make db-check-seed-data
  ```

### CI drift detected
- Generate and commit the missing migration:
  ```bash
  make migration m="fix_schema_drift"
  make migrate-and-seed
  ```

### Multiple heads detected
- Rebase migrations and edit `down_revision` to restore a linear chain (merge revisions are not allowed).

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
- Linear history check:
  ```bash
  make db-linear-history
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

You can allowlist known-safe drift diffs by setting `DYLEN_MIGRATION_DRIFT_ALLOWLIST="token1,token2"` before running drift checks.
