# AGENTS.md — Dylen Engine Guardrails

These instructions apply to the entire repository unless a more specific `AGENTS.md` is added in a subdirectory.

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
- Add line breaks and after the following blocks: [if/else, try/except, loop, with]
- Add comments for all logic implementations. Add docstrings for functions. They should focus on How and Why and less on What.
- No blank lines after the comments, the next line should start with the code directly.

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
- Migrations create schema only; seeds populate data. If startup runs migrations, it must also run seed scripts.
- Seed scripts must not assume prior seed ordering beyond what `seed_versions` enforces.

## HARD Rules
- Prioritize code verification and identifying edge cases over writing comprehensive test suites.
- Focus on fixing failures and implementing requests directly.
- Avoid writing tests for verification, instead verify the code thoroughly.
