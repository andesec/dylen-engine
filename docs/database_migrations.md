# Database Migrations with Alembic

This project uses [Alembic](https://alembic.sqlalchemy.org/) for database schema migrations.

## Configuration

- **Configuration File**: `dylen-engine/alembic.ini`
- **Migration Scripts**: `dylen-engine/alembic/versions/`
- **Environment config**: `dylen-engine/alembic/env.py`

## Common Commands

We provide `make` targets to simplify migration tasks.

### 1. Generating a New Migration

After modifying a SQLAlchemy model in `dylen-engine/app/schema/`, generate a migration skeleton:

```bash
make migration m="Description of change"
```

This will:
1. Compare the current DB state with your SQLAlchemy models.
2. Create a new script in `dylen-engine/alembic/versions/`.
3. **IMPORTANT**: Manually review and edit the generated migration before committing.

### 2. Applying Migrations

Apply all pending migrations to the database:

```bash
make migrate
```

### 3. Downgrading

Downgrades are optional and should be used with caution:

```bash
cd dylen-engine && uv run alembic downgrade -1
```

## Manual Alembic Commands

```bash
cd dylen-engine
uv run alembic revision --autogenerate -m "message"
uv run alembic upgrade head
uv run alembic history
```

## CI Helper Scripts

The following scripts power the migration checks in CI:

- `scripts/db_migration_lint.py` — policy lint checks on migration files
- `scripts/db_check_pr_migration_count.py` — enforces one migration per PR when schema files change
- `scripts/db_check_heads.py` — ensures a single Alembic head
- `scripts/db_migration_smoke.py` — runs migrations on a fresh DB (and upgrade-from-previous)
- `scripts/db_check_drift.py` — detects drift between models and DB

## Production Deployment

- Migrations run in a **dedicated deploy step** (not during app startup).
- Run `alembic upgrade head` in staging before production.
- For destructive changes, follow expand/contract and take backups beforehand.
- If auto-running migrations at startup, enforce a single migration lock (see `docs/production_db_migration_process_spec_fast_api_postgres_alembic.md`).
