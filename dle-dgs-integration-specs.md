# DGS ↔ DLE Integration Specs (Living Doc)

> Purpose: A concise, Codex-followable spec for integrating the DLE web app (frontend) with the DGS backend (JSON lesson generation + validation).

## 0) Glossary

- **DLE**: Dynamic Learning Environment (frontend app)
- **DGS**: Data Generation Service (backend)
- **Generation Job**: One end-to-end run that produces a final validated JSON response

---

# Part A — DLE (Frontend) must implement

## A1) New `index.html` UX (fancy landing + guided flow)

### A1.1 Common user workflow (default)

**Card 1: Generate** → **Card 2: Result** (auto-expands when ready)

#### Card 1 — Step 1: Topic, Prompt, and Config

**Goal:** user provides generation inputs with minimal friction.

**UI requirements**

- Hero header: app name + short tagline.
- A premium-looking layout (mobile-first, iPhone friendly).
- **Card 1 (Generate)** contains:
  - **Topic** (single-line input)
  - **Prompt** (multi-line textarea)
  - **Config (simple + advanced toggle)**
  - Primary CTA: **Generate JSON**
  - Secondary actions: **Load Example**, **Reset**

#### Config: mirror DGS OpenAPI (auto-driven)

**Hard requirement:** do **not** hardcode config fields.

Instead, DLE must **fetch the DGS OpenAPI spec** at runtime and generate config controls from it.

- Source: DGS OpenAPI JSON.
- Approach:
  1. Fetch OpenAPI JSON.
  2. Locate `POST /v1/lessons/generate` → requestBody schema `GenerateLessonRequest`.
  3. Convert fields into UI controls using types, enums, defaults, and required fields.
  4. Render them inside the Config panel.

**Concrete config fields to render (from current OpenAPI)**
Top-level

- `topic` (string, required, minLength 10)
- `prompt` (string | null, optional, **visible textarea** for additional details, maxLength 300)
- `mode` (enum `fast | balanced | best`, default `balanced`)
- `schema_version` (string | null)
- `idempotency_key` (string | null)
- `constraints` (object | null)

Nested: `constraints`

- `primaryLanguage` (enum `English | German | Urdu` )
- `learnerLevel` (enum `Newbie | Beginner | Intermediate | Expert` | null)
- `length` (enum `Highlights | Detailed | Training` | null)

**UX rules for “easy + intuitive” config**

- Keep Card 1 simple:
  - Always show: **Topic** + **Prompt** + **Mode**
  - Prompt: helper text “Optional details to guide lesson generation”
  - Show **Constraints** as 3 simple controls (Language select, Learner Level select, Length select)
- Put `schema_version` and `idempotency_key` behind **Advanced** accordion.
- Pre-fill defaults (Mode = balanced).
- Inline helper text:
  - Mode: “fast = quicker, best = highest quality”
  - Idempotency key: “prevents accidental duplicates”
  - Schema version: “pin output schema version”

> Note: This avoids drift when DGS changes; the UI stays in sync automatically.

---

### A1.2 Step 1.5 — Progress UI (polling)

#### Target UX

After user clicks **Generate JSON**:

- Card 1 locks inputs (read-only) and shows a progress section.
- Show a 3-step timeline:
  1. **Collect** → 2) **Transform** → 3) **Validate**
- Each step supports: `pending | active | done | error`
- Provide **Cancel** button (best-effort; see DGS section)

#### Polling strategy (chosen)

Polling is the simplest for Lambda-based backends (no long-lived connections needed).

**Frontend behavior**

1. Start job (async): `POST /jobs` (or DGS equivalent)
   - Receive `{ jobId }` immediately.
2. Poll: `GET /jobs/{jobId}` on a backoff schedule until done/error.
   - Recommended:
     - 0–10s: every **750ms**
     - 10–30s: every **1500ms**
     - 30s+: every **3000ms**
3. Update progress timeline based on returned `phase/status`.
4. On `done`, collapse Card 1 and expand Card 2.

**Polling UX safeguards**

- Show “Still working…” after \~10s.
- Hard client timeout (e.g., 120s) with actionable error.
- If network drops: pause polling, show “Reconnecting…”, resume.

---

## A2) Result view and layout (Card 2)

### A2.1 Card auto-transition

- When job is `done`:
  - **Collapse Card 1** (keep a small summary row: topic + timestamp + “Edit” button)
  - **Expand Card 2** (Result)

### A2.2 Card 2 contents (common workflow)

Card 2 must include BOTH:

1. **JSON Viewer** (final lesson JSON)
2. **Content Structure panel** (your “content structure” UI section moved here)

**Layout requirement (iPhone screen)**

- Use a split vertical layout inside Card 2:
  - Top: JSON viewer (code editor/viewer)
  - Bottom: Content Structure panel
- Ensure **both are visible at the same time** on iPhone:
  - Make each panel **independently scrollable** (internal scroll)
  - Set fixed max heights using viewport units (e.g., each \~40–45vh) so the card header + buttons still fit.

**Controls**

- Buttons above viewers:
  - Copy JSON
  - Download JSON
  - Start Over
- If validation fails:
  - Highlight “Validate” step as error
  - Show error summary with:
    - error code
    - message
    - path/location (if available)
  - Provide Retry

---

## A3) Advanced user workflow (implemented at page start)

### A3.1 Entry modal (on page load)

On first load (and also accessible via a header button “Switch Mode”), show a modal:

- Title: “How do you want to start?”
- Options:
  1. **Generate lesson JSON** (default)
  2. **Bring your own JSON**

**Behavior**

- If user selects **Generate**:
  - Start at Card 1 (Generate) → follow common workflow.
- If user selects **Bring your own JSON**:
  - Skip Card 1.
  - Open Card 2 immediately with an **empty JSON code viewer**.
  - No backend calls are required for the remainder of this flow.

### A3.2 Advanced capabilities (all local in frontend)

In Advanced mode, Card 2 supports three paths:

1. **Edit JSON directly**
   - Code viewer becomes editable.
   - Provide buttons: Validate (local rules), Format/Prettify, Reset.
2. **Import JSON**
   - Paste into code viewer OR upload a `.json` file, using a button in the top right controls  of the codeviewer widget
   - Parse + show errors in the validation panel as it is now. 
3. **Progressive build using “Partial JSON” widget**
   - Let user assemble JSON in sections.
   - Build on the functionality already present. 

**Important rule:** In “Bring your own JSON” mode, everything happens locally and does **not** trigger DGS generation calls.

---

## A4) Loading & progress visuals (Codex-like)

### A4.1 Codex-style ‘working’ feel

While waiting for DGS (polling flow):

- Use subtle **shimmer / pulse** on the active step row.
- Dim completed steps, highlight the active step.
- Use animated dots on “Generating…” label.

### A4.2 Multi-call progress visualization

DLE must visualize **nested progress** when DGS performs multiple AI calls:

- Example timeline:
  - Collect
    - AI call 1 / 2
  - Transform
  - Validate
- Show:
  - Overall phase (Collect / Transform / Validate)
  - Subphase label (e.g. “AI call 2 of 5”)
- Progress bar should reflect `completed_steps / total_steps` when available.

### A4.3 Animated loader

Integrate the “Glowing Loader Ring Animation”:

- Source: [https://codepen.io/Curlmuhi/pen/ExKWXKO](https://codepen.io/Curlmuhi/pen/ExKWXKO)
- Usage:
  - Inline loader inside progress area
  - Optional fullscreen overlay for initial queue state
- Respect `prefers-reduced-motion`.

---

# Part B — DGS (Backend) must implement

## B0) Current OpenAPI reality (what exists today)

Per the provided OpenAPI file, DGS currently exposes:

- `GET /health`
- `POST /v1/lessons/generate` (synchronous; returns lesson JSON + logs + meta)
- `POST /v1/lessons/validate`
- `GET /v1/lessons/{lesson_id}` (fetch stored lesson)

Auth header on all lesson endpoints:

- Required header: `X-DGS-Dev-Key: string`

**Important:** `/v1/lessons/generate` returns `200` with the final result (not async). If we want real progress UI with polling, DGS must add job endpoints (next section).

## B1) Job-based async generation (required for polling)

### Persistence (hard requirement)

- **All jobs must be persisted in DynamoDB**.
- Reason: Lambda is stateless; polling requires durable state.
- **Results must be stored as a JSON blob in DynamoDB (no S3).**

### Proposed DynamoDB schema (single-table)

**Table name:** `dgs_jobs`

**Primary keys**

- `PK` (string): `JOB#{jobId}`
- `SK` (string): `JOB#{jobId}` (same as PK for single-item jobs)

**Core attributes (job row)**

- `jobId` (string)
- `request` (map)
  - `topic` (string)
  - `prompt` (string | null)
  - `mode` (string)
  - `schema_version` (string | null)
  - `idempotency_key` (string | null)
  - `constraints` (map | null)
- `status` (string): `queued | running | done | error | canceled`
- `phase` (string | null): `collect | transform | validate`
- `subphase` (string | null): e.g. `ai_call_2_of_5`, `section_3_of_12`
- `total_steps` (number | null)
- `completed_steps` (number | null)
- `progress` (number | null)  // 0–100
- `logs` (list)  // bounded length
- `result_json` (map | string)  // final JSON blob; store as Map if possible, else stringified JSON
- `validation` (map | null)
  - `ok` (boolean)
  - `errors` (list)
- `cost` (map)
  - `currency` (string)  // e.g. USD
  - `total_input_tokens` (number)
  - `total_output_tokens` (number)
  - `total_cost` (number)
  - `calls` (list)  // per-AI-call breakdown
- `created_at` (string ISO)
- `updated_at` (string ISO)
- `expires_at` (number epoch seconds)  // TTL

**Secondary access patterns**

- Optional GSI1 (by time):
  - `GSI1PK = JOBS#ALL`
  - `GSI1SK = created_at`
- Optional GSI2 (by idempotency):
  - `GSI2PK = IDEMP#{idempotency_key}`
  - `GSI2SK = created_at`

**Size guardrails**

- DynamoDB item limit is \~400KB. DGS must enforce:
  - Maximum lesson size and compress JSON string to fit. 
  - Bound `logs` length (e.g. last 100 lines)
  - Bound `calls` breakdown length

> If output can exceed limits, DGS must truncate non-essential fields first (logs/calls), and fail gracefully if still too large.

### Job runtime & timeouts

- Job runtime is **variable** and must be configurable.
- DGS should expose config defaults (env vars):
  - `JOB_SOFT_TIMEOUT_SECONDS` (e.g. 30–60s)
  - `JOB_HARD_TIMEOUT_SECONDS` (e.g. 120–180s)
- Status behavior:
  - If soft timeout exceeded → status remains `running`, log warning
  - If hard timeout exceeded → status `error` with timeout code

### Multi-call AI generation (length-aware)

DGS must account for multiple AI calls in json generation stage (using structurer agent) depending on requested lesson length:

- `Highlights` → 1 AI call total
- `Detailed` → **2 AI calls** (each generating half of the content json)
- `Training` → **1 AI call per section** (1 call for generating json of each section, N calls. Max 10 calls)

**Suggested maximum AI calls (guardrails)**

- Highlights: `max_calls = 2`
- Detailed: `max_calls = 6`
- Training: `max_calls = min(24, number_of_sections)`

If the plan would exceed `max_calls`:

- Return an error that advises lowering `length` during the request data validation before processing the request. 

Each AI call must be reflected in job status (`subphase`) and logs.

### Required status model additions

- `phase`: `collect | transform | validate`
- `subphase`: string (e.g. `ai_call_1`, `ai_call_2`, `section_3`, etc.)
- `total_steps`: number (optional)
- `completed_steps`: number (optional)

---

## B2) Phase reporting

DGS must emit phase transitions internally:

1. collect → 2) transform → 3) validate

Even if each phase is fast, still report them so DLE can visualize.

### Required logging + cost accounting per AI call

For every AI call, DGS must log:

- call index (e.g. `ai_call 2/5`)
- purpose (e.g. `collect`, `section_3_generate`, `refine`, `repair`)
- input tokens
- output tokens
- **estimated cost** for that call

Also compute and store totals on the job:

- `total_input_tokens`, `total_output_tokens`, `total_cost`

**How to estimate cost**

- DGS config must include a price table per model (input + output per 1M tokens), e.g.:
  - `MODEL_PRICING_JSON` env var (map)
- Cost formula:
  - `call_cost = (input_tokens/1_000_000)*price_in + (output_tokens/1_000_000)*price_out`
- Store values in `job.cost.calls[]` and roll up to `job.cost.total_cost`.

> Note: If the model/provider does not return token usage, DGS must approximate or mark as unknown.

## B3) Config options for “Generate lesson” (make them explicit in OpenAPI)

**Requirement:** DGS must define a concrete `GenerateLessonRequest` schema in OpenAPI so DLE can auto-render the config UI.

### Proposed `GenerateLessonRequest`

- `topic: string` (required)
- `prompt: string` (required)
- `config: object` (optional) — define as a proper schema, not `additionalProperties: true`

### Proposed `config` fields (initial set)

(These should become real OpenAPI properties with defaults)

- `model: string` (enum of allowed models)
- `temperature: number` (default e.g. 0.4)
- `max_output_tokens: integer` (default)
- `validation_level: "basic" | "strict"` (default: strict)
- `structured_output: boolean` (default: true)
- `language: string` (default: "en")

> Update these to match what DGS truly supports once implemented; the key is: **define them in OpenAPI** so DLE mirrors them.

## B4) Cancellation (nice-to-have)

- Endpoint: `POST /v1/jobs/{jobId}/cancel`
- Behavior: best-effort (may return “too late” if already done)

## B5) OpenAPI as source of truth

- DGS OpenAPI must accurately define:
  - generation/job endpoints
  - request/response schemas
  - enums/defaults for config
- DLE will generate config UI by introspecting this OpenAPI.

---

## B6) Future API: Writing task checking (async job-based)

### Goal

Support checking user-written responses against lesson-defined criteria.

### Key idea

- **Checking criteria are defined inside the lesson JSON itself**.
- DLE sends:
  - User-written text
  - Relevant lesson section JSON (criteria)
- DGS evaluates and returns structured feedback.

### Job-based API (to be finalized later)

- `POST /v1/writing/check`

  - Request:
    - `text: string`
    - `criteria: object` (from lesson JSON)
  - Response (202): `{ jobId }`

- `GET /v1/jobs/{jobId}`

  - Same status shape as lesson generation jobs.
  - Final `result` contains:
    - `ok: boolean`
    - `issues: []`
    - `feedback: string`

(No criteria schema yet — intentionally deferred.)
