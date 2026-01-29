# Database Migration Guide

This repository follows the production migration process defined in `docs/production_db_migration_process_spec_fast_api_postgres_alembic.md`.

## CI/CD Automation

### Pull Requests (`pr-migration-check.yml`)
Every PR touching engine code runs migration checks:
- One-migration-per-PR enforcement when schema files change (`scripts/db_check_pr_migration_count.py`)
- Migration lint & policy checks (`scripts/db_migration_lint.py`)
- Single Alembic head check (`scripts/db_check_heads.py`)
- Fresh DB migration smoke test (`scripts/db_migration_smoke.py --mode fresh`)
- Upgrade-from-previous revision smoke test (`scripts/db_migration_smoke.py --mode upgrade-from-previous`)
- Drift detection (`scripts/db_check_drift.py`)

## Development Workflow

1. Ensure local DB is at head:
   ```bash
   make migrate
   ```
2. Modify models in `dylen-engine/app/schema/`.
3. Generate a migration skeleton:
   ```bash
   make migration m="short_description"
   ```
4. **Manually edit** the migration for safety and ordering.
5. Apply migrations:
   ```bash
   make migrate
   ```
6. Commit the migration file.

> Note: Autogenerate output is only a starting point. Never ship unedited autogenerate migrations.

## Lint Tags

Migration lint recognizes explicit tags for exceptional cases:
- `# destructive: approved` — required for `drop_table` / `drop_column` in `upgrade()`
- `# empty: allow` — allow empty merge revisions
- `# backfill: ok` — acknowledge backfill for `nullable=False` changes
- `# type-change: approved` — required for type changes in `upgrade()`

Drift detection supports an explicit allowlist:
- `DYLEN_MIGRATION_DRIFT_ALLOWLIST="token1,token2"` filters known-safe diffs by substring.

## Production Workflow

- Migrations run in a **dedicated deploy step** (not at service startup).
- Staging must succeed before production.
- Use `alembic upgrade head` and maintain a single Alembic head on `main`.
- Follow expand/contract for breaking changes and ensure backups are taken before destructive steps.

## Manual Alembic Operations

```bash
cd dylen-engine
uv run alembic current
uv run alembic history
uv run alembic stamp <revision_id>
```

## Notes on Safety

- Use `CREATE INDEX CONCURRENTLY` for large tables via `app.core.migrations.create_index_concurrently`.
- Avoid destructive changes without explicit review sign-off.
- If downgrades are needed, document exceptions for lossy migrations.
