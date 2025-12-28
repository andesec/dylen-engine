# DGS (Data Generation Service) Spec — Backend for DLE

## 1) Purpose

**DGS** is a backend service for **DLE (Dynamic Learning Environment)**.

Top priority (MVP): **Generate valid DLE lesson JSON from a topic** + **store/retrieve past JSON**.

Secondary (later MVPs): self-repair + fine-tuning, then auth/ACL, then marketing/monetization/community.

Key constraints:

- **Local-first**: everything must run + debug locally without friction.
- **Serverless-first** on AWS, but **easy to move off Lambda** later with minimal code changes.
- **Always-free tier focus** until monetized.
- **Secure-by-default**, efficient, and user-friendly.

---

## 2) Architecture (portable, always-free friendly)

### DLE (client)

- Static web app (GitHub Pages today; optional S3/CloudFront later).
- Renders lesson JSON and runs all widget logic client-side.
- Never stores provider keys.

### DGS (backend)

- **FastAPI ASGI app** as the primary artifact.
- Deploy options (same codebase):
  1. **Local**: `uvicorn app.main:app`
  2. **AWS Lambda**: FastAPI wrapped by `mangum` (ASGI → Lambda)
  3. **Non-Lambda compute later**: container/ECS/EC2/any ASGI host (no app code changes)

### AWS entrypoint choice (to stay “always-free” longer)

- Prefer **Lambda Function URLs** for HTTP endpoints (no API Gateway requirement).
- Use API Gateway only when needed for advanced features; note its free tier is time-limited for new accounts.

### Storage (min infra)

- **Primary MVP storage: DynamoDB only**
  - Store **JSON blobs** (must fit DynamoDB item limits) + metadata + tags.
  - This keeps infra minimal and aligns with DynamoDB’s always-free allocation.
- **Optional later**: S3 for large JSON blobs or versions (S3 is cheap, but not strictly “always-free”).

---

## 3) AI design (two-step pipeline for cost + quality)

DGS uses AI in **two distinct ways**:

### Step A — Data Gatherer (high-quality model)

Goal: Generate a **rich learning dataset** from a topic. Output: an internal **Intermediate Data Model (IDM)** (JSON), e.g.

- vocabulary lists, concepts, examples, exercises, constraints, metadata
- optionally includes citations/URLs if web context is enabled (v2)

### Step B — JSON Structurer (low-cost model)

Goal: Convert IDM → **final DLE lesson JSON** (strict schema).

**Hard requirement:** Step B must use the model/provider **structured output (JSON) endpoint/mode** (i.e., an API feature that guarantees JSON-typed output or enforces a JSON schema / JSON mode). This is mandatory to reduce formatting errors and improve determinism.

Output: **schema-valid lesson JSON only** (no markdown).

Implementation requirements:

- Use the provider’s JSON/structured-output mechanism for Step B whenever supported.
- If a provider does not support structured output for the chosen model, DGS must either:
  1. switch to a model that does, or
  2. fail the request with a clear error indicating structured output is unavailable.

### Why this works

- Expensive reasoning/data generation happens once (Step A).
- Cheap formatting/structuring happens in Step B.
- IDM can be cached + reused for variants (difficulty, language, length) without re-gathering.

### OpenAI Agents SDK requirement

- Use **OpenAI Agents SDK** for orchestration and tracing:
  - `GathererAgent` → produces IDM
  - `StructurerAgent` → produces lesson JSON
  - `RepairAgent` → fixes invalid JSON (if enabled)
- Providers remain pluggable (Gemini dev, OpenRouter prod).

---

## 4) JSON correctness: schema + widgets validation, repair, and fine-tuning

### Pydantic schema models (hard requirement)

- Define **Pydantic v2 models** for the DLE lesson JSON schema (the same structure DLE renders).
- Validation must be performed by constructing the Pydantic model (not “best effort” parsing).
- Use:
  - discriminated unions for widget items (by widget key)
  - strict types (`StrictStr`, `StrictInt`, etc.) where useful
  - `extra = "forbid"` to prevent unknown fields
  - versioned root model (support `schema_version`)
- Expose a single API:
  - `validate_lesson(payload: dict) -> (ok: bool, errors: list, model?: Lesson)`
- Optional: export JSON Schema from Pydantic for tooling/CI checks.

### widgets.md as source of truth (generation + validation)

DGS must **always** reference `widgets.md`:

- **Generation**: prompts for Structurer/Repair must embed (or reference) the allowed widgets and each widget’s expected shape/rules from `widgets.md`.
- **Validation**: implement a `WidgetRegistry` loaded from `widgets.md` at startup and enforce:
  - only widget types present in `widgets.md` are allowed
  - required fields / array shapes match the widget definition
  - any “shorthand array positions” rules are enforced

Implementation note:

- Keep `widgets.md` in-repo for DGS (pinned version) and treat changes as a versioned artifact (`widgets_version`).
- If DLE owns `widgets.md`, DGS should vendor it (copy into DGS repo) or fetch it at build time and pin the hash.

### Validation (hard requirement)

- Validate final output against:
  1. **Pydantic schema** (structural correctness)
  2. **WidgetRegistry rules** from `widgets.md` (semantic/widget correctness)
- Fail fast with structured error list (path + message + rule source).

### Self-repair (high priority, after basic generation)

- Max **1 repair attempt** per request (feature-flag).
- Repair prompt includes:
  - invalid JSON
  - validation errors (both schema + widget rules)
  - instruction: output corrected JSON only

### Fine-tuning (future)

- DGS persists a “repair dataset” (IDM + invalid JSON + corrected JSON + error list).
- This dataset is used later for fine-tuning or distillation to improve Step B and reduce repairs.

---

## 5) MVP phases (each phase is deployable to AWS + runnable locally)

The ordering below matches the priority list provided.

### Phase 0 — Foundation (deployable dev shell)

Deliverables:

- FastAPI app skeleton + health endpoint
- Provider stubs (Gemini/OpenRouter) behind a common interface
- Schema validator module
- Local dev tooling (`uvicorn`, `.env`, simple makefile/scripts)
- AWS deployment template (SAM) for a single Lambda + Function URL

Quality bar:

- Local run and AWS deployment both work with the same routes.

### Phase 1 — Core MVP: topic → lesson JSON + storage

Deliverables:

- `POST /v1/lessons/generate`:
  - Step A gatherer (Gemini dev)
  - Step B structurer (low-cost model; configurable)
  - validate → store → return
- DynamoDB persistence:
  - store lesson JSON blob + minimal metadata
- `GET /v1/lessons/{lesson_id}`

Security posture (until auth exists):

- Endpoint protected by **server-side shared secret header** (e.g., `X-DGS-Dev-Key`) + strict CORS.

### Phase 2 — JSON storage UX: list, tag, cache

Deliverables:

- `GET /v1/lessons` (pagination)
- `PATCH /v1/lessons/{lesson_id}` (tags/title)
- Idempotency key support (dedupe repeated generate taps)
- Caching:
  - Cache IDM and/or final JSON by `(topic + constraints + schema_version + prompt_version)`
  - TTL-based eviction

### Phase 3 — Quality upgrades: self-repair + evaluation harness

Deliverables:

- One-pass self-repair (feature flag)
- Persist repair dataset
- Offline evaluation script:
  - runs a test set of topics
  - reports schema pass rate, repair rate, latency, and approximate cost

### Phase 4 — Authentication + Authorization + ACL (Cognito + Google)

Deliverables:

- Cognito Hosted UI with Google as IdP
- JWT verification in DGS
- Per-user data partitioning + ACL enforced
- Migrate data model from “dev key global” to `USER#{sub}` partitioning

### Phase 5 — Marketing page

Deliverables:

- Polished landing page + docs
- Basic product analytics (privacy-safe)

### Phase 6 — Monetization

Deliverables:

- Payments/subscriptions
- Usage-based quotas + metering

### Phase 7 — Feedback/support

Deliverables:

- User feedback flow + support tooling

### Phase 8 — Scoreboard + sharing + community

Deliverables:

- Public/shared lesson links
- Community features and moderation rules

---

## 6) API contract (FastAPI)

### Headers

- `Authorization: Bearer <token>` (Phase 4+)
- `X-DGS-Dev-Key: <secret>` (Phase 1–3 only)

### Endpoints

**POST** `/v1/lessons/generate`

- Request:
  - `topic: string` (required)

  - `constraints?: object` (learnerLevel -> “Newbie”|”Beginner”|”Intermediate”|”Expert”, language, length -> “Highlights”|”Detailed”|”Training”)

  - `schema_version?: string`

  - `idempotency_key?: string`

  - `mode?: "fast"|"balanced"|"best"` (maps to model choices)
- Response:
  - `lesson_id: string`
  - `lesson_json: object`
  - `meta: { provider_a, model_a, provider_b, model_b, latency_ms }`

**GET** `/v1/lessons`

- Query: `tag`, `q`, `from`, `to`, `limit`, `cursor`

**GET** `/v1/lessons/{lesson_id}`

**PATCH** `/v1/lessons/{lesson_id}`

- `tags_add?`, `tags_remove?`, `title?`

**GET** `/v1/me` (Phase 4+)

---

## 7) Data model (DynamoDB-first)

### Table: `Lessons`

**Phase 1–3 (dev key / single-tenant)**

- `pk = TENANT#default`
- `sk = LESSON#{created_at_iso}#{lesson_id}`

**Phase 4+ (multi-tenant)**

- `pk = USER#{sub}`
- `sk = LESSON#{created_at_iso}#{lesson_id}`

Attributes:

- `lesson_id` (UUID)
- `topic`, `title`
- `tags` (StringSet)
- `created_at`
- `schema_version`, `prompt_version`
- `idempotency_key` (optional)
- `provider_a`, `model_a` (gatherer)
- `provider_b`, `model_b` (structurer)
- `lesson_json` (string or binary if compressed)
- `status` (ok|invalid|deleted)

Optional indexes:

- GSI: `lesson_id` lookup

---

## 8) Security (non-negotiable)

- No AI provider keys in DLE client.
- Strict CORS (only DLE origins).
- Input limits (topic length, payload size).
- Rate limiting (per IP or tenant or per user; DynamoDB token bucket).
- Secrets in env + AWS Secrets Manager later.
- If “web context” tool is enabled later:
  - allowlist domains
  - SSRF protection (block private IP ranges)
  - size/time limits
  - cache fetched content

---

## 9) Performance & efficiency

- Two-step AI pipeline to minimize expensive calls.
- Cache IDM + final JSON.
- Keep Lambda cold-start light (minimal deps).
- Limit log volume; set log retention.

---

## 10) Local development & debugging

Must support:

- Pure local run: `uvicorn` with `.env`
- Local AWS-style invocation: AWS SAM local invoke
- Local DynamoDB: DynamoDB Local (docker)
- Docker compose to setup and run everything flawlessly in one command. 

No feature should require “deploy first to debug.”

---

## 11) Repo layout (Codex should generate)

```
/dgs-backend
  app/
    main.py                    # FastAPI routes
    lambda_handler.py          # Mangum adapter (Lambda only)
    config.py                  # env + settings

    schema/
      widgets.md               # vendored/pinned source of truth
      widgets_loader.py        # parses widgets.md into WidgetRegistry
      lesson_models.py         # Pydantic v2 models for lesson JSON
      validate_lesson.py       # schema + widget validation entrypoint

    auth/                      # Phase 4+
      cognito_jwt.py

    ai/
      orchestrator.py          # Agents SDK wiring
      providers/
        base.py                # interfaces (SOLID)
        gemini.py
        openrouter.py
      prompts/
        gatherer.md
        structurer.md
        repair.md
      router.py                # selects provider/model by mode

    storage/
      lessons_repo.py          # interface
      dynamodb_repo.py

    utils/
      rate_limit.py
      ids.py
      logging.py

  tests/
    unit/
    integration/

  infra/
    sam-template.yaml

  docker-compose.yml           # DynamoDB Local + DGS local run
  README.md
  pyproject.toml
```

---

## 12) Codex implementation rules

### Clean code + SOLID (hard requirement)

- Use interfaces for provider and storage layers (Dependency Inversion).
- Keep orchestration (Agents) separate from transport (FastAPI) and persistence.
- One module = one responsibility; avoid “god” files.
- Prefer pure functions for validation and prompt assembly.

### Readability + documentation

- Full type hints everywhere.
- Docstrings on public functions/classes.
- Clear, minimal inline comments explaining *why* (not what).
- Small functions, predictable naming, consistent error handling.

### Security + correctness

- Keep DGS stateless.
- Validate JSON before storing (schema + widgets.md rules).
- No provider keys in DLE.
- Strict CORS + input limits.

### Efficiency

- Keep dependencies minimal (Lambda cold start).
- Cache compiled validators/registry at startup.
- Max **2 AI calls** per request in Phase 3+ (gather + structure; optional single repair).

### Portability

- Preserve portability: AWS-specific code lives only in `infra/` and `lambda_handler.py`.
- The FastAPI app must run unchanged on `uvicorn` and on Lambda.

### Tooling (recommended defaults)

- Formatting/linting: `black` + `ruff`
- Type checking: `mypy`
- Tests: `pytest` (unit + integration)
- Pre-commit hooks configured in repo

