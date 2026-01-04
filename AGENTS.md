NOTE: Prioritize and follow architecture-refactor-specs.md over dle-dgs-integration-specs.md

## Engineering guardrails

- Secure-by-default posture; avoid introducing permissive defaults.
- Local-first and serverless-first design preferences.
- Enforce strict CORS; do not expose provider API keys in any client bundle.
- Keep dependencies minimal to improve cold-start performance.
- Follow SOLID principles with clear separation of transport, orchestration, and storage concerns.
- Use full type hints and docstrings throughout.
- Default tooling standards: `black`, `ruff`, `mypy`, and `pytest`.

## Coding Standards (Strict)
- keep function definitions and call parameters on a single line unless the signature exceeds 120 characters, in which case keep them in as fewer lines as possible.
- Add line breaks before and after the following blocks: [if/else, try/except, loop, with]
- Add comments for all logic implementations. Add docstrings for functions. They should focus on How and Why and less on What.

## Workflow expectations

- Before opening a PR, run: `make format lint typecheck test`.
- Keep AWS-specific code confined to `infra/` or `lambda_handler.py`.
- Keep `openapi.json` updated whenever API endpoints change.
