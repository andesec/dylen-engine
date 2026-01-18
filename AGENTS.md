## Engineering guardrails

- Secure-by-default posture; avoid introducing permissive defaults.
- Local-first and serverless-first design preferences.
- Enforce strict CORS; do not expose provider API keys in any client bundle.
- Keep dependencies minimal to improve cold-start performance.
- Follow SOLID principles with clear separation of transport, orchestration, and storage concerns.
- Use full type hints and docstrings throughout.
- Default tooling standards: `ruff`, `mypy`, and `pytest`.

## Coding Standards (Strict)
- Always keep method parameters, arguments, and signatures on the same line.
- Add line breaks and after the following blocks: [if/else, try/except, loop, with]
- Add comments for all logic implementations. Add docstrings for functions. They should focus on How and Why and less on What.
- No blank lines after the comments, the next line should start with the code directly.

## Workflow expectations
- Don't unnecessarily format a file or code if there is no change in the code there.
- Ignore Blank line issues in the code!
- Before opening a PR, run: `make format lint typecheck test`. (always!)
- Keep `openapi.json` updated whenever API endpoints change.
