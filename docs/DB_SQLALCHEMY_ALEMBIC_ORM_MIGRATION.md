# Database Migration Spec: SQLAlchemy ORM + Alembic (Repo-wide)

## Prompt

Convert all database initializations, usage, models, and tables to use SQLAlchemy with Alembic. All DB operations must use the ORM framework and use model objects for CRUD operations.

## Current State (as of implementation start)

- SQLAlchemy Async engine/session exists in `dgs-backend/app/core/database.py`.
- Alembic is configured in `dgs-backend/migrations/` and migrations exist under `dgs-backend/migrations/versions/`.
- ORM models exist for:
  - `users` (in `dgs-backend/app/schema/sql.py`)
  - `dgs_jobs` (in `dgs-backend/app/schema/jobs.py`)
  - `dgs_lessons` (in `dgs-backend/app/schema/lessons.py`)
  - `llm_call_audit` (in `dgs-backend/app/schema/audit.py`)
  - `email_delivery_logs` (in `dgs-backend/app/schema/email_delivery_logs.py`)
- Job/Lesson persistence is implemented via repositories that create ORM model instances and commit using `AsyncSession`.

### Gaps / Issues Identified

1. **Async repository mismatch**
   - Repository interfaces (`dgs-backend/app/storage/jobs_repo.py`, `dgs-backend/app/storage/lessons_repo.py`) declare synchronous methods, while implementations are `async def`.
   - API routes still use `run_in_threadpool(repo.create_*)` and `run_in_threadpool(repo.get_*)` for operations that are already async, which is incorrect and can lead to un-awaited coroutine warnings and inconsistent behavior.

2. **Non-uniform DB access**
   - Some routes access ORM models directly using `AsyncSession` (`users`, `admin approval`), while others use repositories. This is acceptable as long as all access is via SQLAlchemy ORM (not raw SQL), but should be standardized where it improves maintainability.

3. **Alembic/ORM alignment**
   - Any new tables must have corresponding Alembic migrations.
   - Alembic env must import ORM models so autogenerate can discover metadata (already done, but must remain correct).

## Goals

- All DB CRUD operations use SQLAlchemy ORM (no psycopg cursors, no raw SQL strings in application code).
- All schema changes are managed via Alembic migrations.
- DB access patterns are consistent and safe in async contexts.

## Non-Goals (for this iteration)

- Refactoring the entire application into a strict repository-only pattern for every model.
- Fixing repo-wide mypy issues unrelated to database access (mypy currently fails due to pre-existing errors).

## Requirements (Acceptance Criteria)

### ORM usage

- [ ] No application code uses raw SQL strings for CRUD.
- [ ] ORM `mapped_column` models exist for every persisted table.
- [ ] CRUD uses ORM queries (`select(Model)`, `session.add`, `session.get`, etc.).

### Async correctness

- [ ] No `run_in_threadpool(...)` is used for repository methods that are already async.
- [ ] Repository protocols accurately reflect async APIs.

### Alembic governance

- [ ] Every new or changed table/column/index has an Alembic migration.
- [ ] Alembic `env.py` reliably imports model metadata.

### Reliability & safety

- [ ] Session lifecycle is consistent (use shared session factory; avoid global session objects).
- [ ] DB writes commit before side-effect operations that should not block persistence.

## Implementation Plan

### Phase 1: Fix async repository contract + call-sites (required)

1. Update repository protocols to declare async methods:
   - `dgs-backend/app/storage/jobs_repo.py`
   - `dgs-backend/app/storage/lessons_repo.py`
2. Remove `run_in_threadpool` usage for DB operations that are already async:
   - `dgs-backend/app/api/routes/lessons.py`
   - `dgs-backend/app/api/routes/writing.py`
3. Ensure imports and typing remain consistent after refactor.

### Phase 2: Standardize ORM CRUD

1. Where appropriate, centralize CRUD in repositories/services to minimize scattered queries.
2. Add repository/service for `User` CRUD if admin/user management grows.

### Phase 3: Alembic enforcement (ongoing)

1. Add migrations for any new models/tables.
2. Ensure model registration remains correct (imports in `app/schema/sql.py` and `migrations/env.py`).

## Validation Checklist

- Run `make format lint test`.
- Run `make typecheck` (expected to fail currently due to existing repo-wide issues; does not block DB correctness).

