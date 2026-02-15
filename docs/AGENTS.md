# AGENTS.md — Dylen Engine Guardrails

These instructions apply to the entire repository unless a more specific `AGENTS.md` is added in a subdirectory.

## Build, Run, and Test

- **Install**: `make install` (uses `uv sync --all-extras`)
- **Run dev**: `make dev` (starts Postgres + FastAPI with hot reload on port 8080)
- **Stop dev**: `make dev-stop`
- **Lint**: `make lint` (ruff check)
- **Format**: `make format` (ruff format) and `make format-check` to verify
- **Type check**: `make typecheck` (mypy)
- **Test**: `make test` (pytest)
- **Generate OpenAPI**: `make openapi` (updates `openapi.json`)
- **Migrations**: Use `alembic upgrade head` (idempotent) and seed runners; migrations are schema-only

## Architecture

FastAPI backend ([app/main.py](app/main.py)) with modular structure:
- **API routes** (`app/api/routes/`): Feature-organized routers (auth, lessons, jobs, etc.) included in main app
- **Services** (`app/services/`, `app/ai/`, `app/storage/`): Business logic and provider integrations
- **Schema** (`app/schema/`): Pydantic models with strict validation; all endpoints return `DecimalJSONResponse`
- **Core** (`app/core/`): Exception handlers, middleware (CORS, security headers, request logging), lifespan, JSON encoder
- **Storage** (`app/storage/`): Database layer (SQLAlchemy async, PostgreSQL, Alembic for migrations)
- **Config** ([app/config.py](app/config.py)): Runtime config with validation; required environment variables defined and fail-fast on startup

Key patterns:
- All async/await throughout (FastAPI + SQLAlchemy asyncio)
- CORS disabled globally (`docs_url=None`, `redoc_url=None`, `openapi_url=None`)
- Middleware stack for logging, security headers, request validation
- Feature flags and quotas managed via runtime config and database

## Engineering guardrails
- Secure-by-default posture; avoid introducing permissive defaults.
- Local-first and serverless-first design preferences.
- Enforce strict CORS; do not expose provider API keys in any client bundle.
- Keep dependencies minimal to improve cold-start performance.
- Follow SOLID principles with clear separation of transport, orchestration, and storage concerns.
- Use full type hints and docstrings throughout.
<!-- - Default tooling standards: `ruff`, `mypy`, and `pytest`. -->

## Coding Standards (Strict)
- Always keep method parameters, arguments, and signatures on the same line.
- Add line breaks after the following blocks: [if/else, try/except, loop, with]
- Add comments for all logic implementations. Add docstrings for functions. They should focus on How and Why and less on What.
- No blank lines after the comments, the next line should start with the code directly.
- Async patterns: All database and I/O operations use `async`/`await`. Use `Session.execute()` with SQLAlchemy ORM for queries. Router functions are `async def`.
- Exception handling: Raise `HTTPException` for API errors (avoid bare `Exception`). Use custom exceptions in `app.core.exceptions` when needed.

## Workflow expectations
- Don't unnecessarily format a file or code if there is no change in the code there.
- Ignore Blank line issues in the code!
<!-- - Before opening a PR, run: `make format lint typecheck test`. (always!) -->
- Keep `openapi.json` updated whenever API endpoints change.

## Database + Seed Safety
- When inserting into `JSONB` columns via raw `text()` SQL, always JSON-encode the value and cast to `::jsonb`.
- Prefer SQLAlchemy `insert()` with JSONB-typed columns when possible to avoid driver encoding issues.
- Seed scripts must remain idempotent: use `ON CONFLICT` upserts and avoid destructive deletes.
- Seed runners should log which scripts are run and skipped.

## Runtime Config Integrity
- New runtime-config keys must define:
  - `_RUNTIME_CONFIG_DEFINITIONS`
  - validation in `_validate_value` (if non-trivial)
  - fallback in `_env_fallback`
- When using feature flags to gate quotas, ensure the quota response hides disabled features.

## Migrations + Seeds
- **Alembic auto-generates migrations**: Use `python3 scripts/db_migration_autogen.py --message "description"` to auto-generate database schema changes based on SQLAlchemy model updates. Never write migrations manually.
- Migrations create schema only; seeds populate data. If startup runs migrations, it must also run seed scripts.
- Seed scripts must not assume prior seed ordering beyond what `seed_versions` enforces.

## HARD Rules
- Prioritize code verification and identifying edge cases over writing comprehensive test suites.
- Focus on fixing failures and implementing requests directly.
- Avoid writing tests for verification, instead verify the code thoroughly.
