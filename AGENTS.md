## Engineering guardrails

- Secure-by-default posture; avoid introducing permissive defaults.
- Local-first and serverless-first design preferences.
- Enforce strict CORS; do not expose provider API keys in any client bundle.
- Keep dependencies minimal to improve cold-start performance.
- Maintain SOLID layering with clear separation of transport, orchestration, and storage concerns.
- Use full type hints and docstrings throughout.
- Default tooling standards: `black`, `ruff`, `mypy`, and `pytest`.

## Workflow expectations

- Before opening a PR, run: `make format lint typecheck test`.
- Keep AWS-specific code confined to `infra/` or `lambda_handler.py`.
- Keep `openapi.json` updated whenever API endpoints change.
