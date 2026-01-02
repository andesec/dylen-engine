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
  2. Locate `POST /v1/jobs` → requestBody schema `GenerateLessonRequest` (fallback: `POST /v1/lessons/jobs`, then `POST /v1/lessons/generate` if jobs endpoints aren’t present).
  3. Convert fields into UI controls using types, enums, defaults, and required fields.
  4. Render them inside the Config panel.

**Concrete config fields to render (from OpenAPI)**

Top-level

- `topic` (string, required)
- `prompt` (string | null, optional, **visible textarea** for additional details)
- `mode` (enum `fast | balanced | best`, default `balanced`)
- `schema_version` (string | null)
- `idempotency_key` (string | null)
- `constraints` (object | null)
- `models` (object | null)  // agent model selection

Nested: `constraints`

- `primaryLanguage` (enum `English | German | Urdu`)
- `learnerLevel` (enum `Newbie | Beginner | Intermediate | Expert` | null)
- `depth` (enum `2..10` as strings | null)  // total sections

Nested: `models`

- `knowledge_model` (enum; Gemini or OpenRouter)
- `structurer_model` (enum; Gemini or OpenRouter)

**UX rules for “easy + intuitive” config**

- Keep Card 1 simple:
  - Always show: **Topic** + **Prompt** + **Mode**
  - Prompt helper: “Optional details to guide lesson generation”
  - Show **Constraints** as 3 simple controls (Language select, Learner Level select, Depth select)
  - Show Models as 2 selects (Knowledge model, Structurer model)
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
   - Body: `GenerateLessonRequest` (same shape as `/v1/lessons/generate`)
   - Include header `X-DGS-Dev-Key: <key>`
   - Receive `{ jobId }` immediately.
2. Poll: `GET /jobs/{jobId}` on a backoff schedule until done/error.
   - Include header `X-DGS-Dev-Key: <key>`
   - Recommended:
     - 0–10s: every **750ms**
     - 10–30s: every **1500ms**
     - 30s+: every **3000ms**
3. Update progress timeline based on returned `phase/status`.
4. On `done`, collapse Card 1 and expand Card 2.

**Polling UX safeguards**

- Show “Still working…” after ~10s.
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
  - Set fixed max heights using viewport units (e.g., each ~40–45vh) so the card header + buttons still fit.

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
   - Paste into code viewer OR upload a `.json` file, using a button in the top right controls of the codeviewer widget
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

DLE must visualize **nested progress** when DGS performs multiple LLM calls:

- Example timeline:
  - Collect
    - KnowledgeBuilder call 1 / 3
  - Transform
    - Structuring section 4 / 8
  - Validate
- Show:
  - Overall phase (Collect / Transform / Validate)
  - Subphase label (e.g. “struct_section_4_of_8”)
- Progress bar should reflect `completed_steps / total_steps` when available.

### A4.3 Animated loader

Integrate the “Glowing Loader Ring Animation”:

- Source: https://codepen.io/Curlmuhi/pen/ExKWXKO
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

### Generation pipeline (agent-based; source of truth)

A generation job is executed as a **4-agent pipeline** (agents 3 & 4 are deterministic code, not LLMs):

#### Agent 1 — KnowledgeBuilder (LLM)

**Goal:** collect learning material for the requested topic using the configured learner constraints.

**Inputs**
- `topic`
- `prompt` (optional)
- `constraints`:
  - `primaryLanguage`
  - `learnerLevel`
  - `depth` (2–10 sections)
- `knowledge_model` (Gemini or OpenRouter)

**Output format (TEXT ONLY; strict)**
- Agent 1 must return **batches**, where **each batch contains exactly 2 sections** in the following format:

```text
Section 1 - Title for this section
Summary ...
Data ....
Key points ...
Practice work ....
Knowledge check ...

Section 2 - Title for this section
Summary ...
Data ....
Key points ...
Practice work ....
Knowledge Check ...
```

**Depth → number of sections**
- `constraints.depth` controls total sections: **2 to 10**.
- Since each batch contains 2 sections, the number of Agent 1 LLM calls is:
  - `knowledge_calls = ceil(depth / 2)`

**Extraction & intermediate artifacts**
- For each batch response, DGS must run a deterministic **regex-based extractor** to split the response into the two sections.
- Each extracted section becomes a single “section data file” (one per section).
- Implementation detail: DGS may write these as temporary files (e.g., `/tmp/job/{jobId}/sections/section_{i}.txt`) during execution, but **must not rely on filesystem persistence** across invocations.
- For debugging/polling, DGS should store a bounded summary of extracted sections in DynamoDB (e.g., titles + short snippets), but avoid storing full raw text if it risks the 400KB item limit.

#### Agent 2 — Lesson Planner & Structurer (LLM)

**Goal:** convert each extracted section into lesson JSON following `widgets.md` + the section/subsection schema.

**Inputs per section**
- `section_data` from Agent 1
- `constraints` (language/level/depth)
- `schema_version` (if provided)
- `structurer_model` (Gemini or OpenRouter)

**Behavior**
- For each section, Agent 2:
  1) Splits content into subsections (more subsections when depth is higher)
  2) Selects appropriate interactive widgets per subsection (must be valid per `widgets.md`)
  3) Produces a **structured JSON output** for *that single section*

> Note: For Gemini, use structured outputs / JSON Schema (native) rather than prompt-only JSON.

#### Agent 3 — Checker & Repairer (Deterministic code)

**Goal:** validate and repair the per-section JSON produced by Agent 2.

- Runs deterministic checks against:
  - JSON parse validity
  - required keys / known widget names
  - common LLM mistakes (trailing commas, markdown fences, `NaN`, comments, stray URLs, etc.)
- Applies deterministic repairs using regex/AST transforms.
- If still invalid after the final repair pass, the section is returned to **Agent 2 for regeneration** (bounded retries).

#### Agent 4 — Stitcher (Deterministic code)

**Goal:** assemble the final lesson JSON.

- Takes the validated per-section objects (from Agent 3), orders them, and stitches them into a single lesson object that **must conform to `widgets.md` and the top-level lesson schema**.
- Final output must be JSON (object), not a string.

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
  - `models` (map | null)
- `status` (string): `queued | running | done | error | canceled`
- `phase` (string | null): `collect | transform | validate`
- `subphase` (string | null)
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
  - `calls` (list)  // per-LLM-call breakdown
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

- DynamoDB item limit is ~400KB. DGS must enforce:
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

### Multi-call LLM usage (depth-aware; agent-based)

DGS must account for multiple LLM calls driven primarily by `constraints.depth` (2–10 sections):

**Agent 1 (KnowledgeBuilder)**
- Emits **2 sections per call**.
- Calls: `knowledge_calls = ceil(depth / 2)`

**Agent 2 (Planner/Structurer)**
- Produces **one JSON section object per call**.
- Calls: `structurer_calls = depth`

**Total LLM calls**
- `total_calls = knowledge_calls + structurer_calls` (Agent 3/4 are deterministic)

**Guardrails (hard limits)**
- `depth` is capped at 10.
- Additionally enforce:
  - `MAX_KNOWLEDGE_CALLS` (default 5)
  - `MAX_STRUCTURER_CALLS` (default 10)
  - `MAX_TOTAL_CALLS` (default 15)

If the plan exceeds any limit:
- Reject the request during validation with an actionable error (e.g., “Lower depth”).

**Retries / regeneration bounds**
- Per-section regeneration due to Agent 3 failures must be bounded:
  - `MAX_STRUCTURER_RETRIES_PER_SECTION` (default 2)


Each LLM call must be reflected in job status (`subphase`) and logs.

```md

**Recommended `total_steps` / `completed_steps` semantics (for DLE progress bars)**
- `total_steps = knowledge_calls + depth /*extract*/ + depth /*structure*/ + depth /*repair*/ + 1 /*stitch*/ + 1 /*final_validate*/`
- Increment `completed_steps` after each step completes; keep `subphase` aligned to the current step.
- If you choose a different counting scheme, keep it stable and documented so DLE can render progress consistently.
```

### Required status model additions

- `phase`: `collect | transform | validate`
- `subphase`: string
- `subphase` MUST encode agent progress, examples:
  - `kb_call_1_of_3` (KnowledgeBuilder call)
  - `extract_section_4_of_8`
  - `struct_section_4_of_8`
  - `repair_section_4_of_8`
  - `stitch_sections`
- `total_steps`: number (optional)
- `completed_steps`: number (optional)

---

## B2) Phase reporting

DGS must emit phase transitions internally:

1. collect (Agent 1: KnowledgeBuilder + extraction)
2. transform (Agent 2: structuring + Agent 3: repair + Agent 4: stitch)
3. validate (final schema validation against widgets.md)

Even if each phase is fast, still report them so DLE can visualize.

### Required logging + cost accounting per LLM call

For every LLM call (Agent 1 + Agent 2), DGS must log:

- call index (e.g. `kb_call 2/3`, `struct_section 4/8`)
- agent (e.g. `KnowledgeBuilder` or `PlannerStructurer`)
- purpose (e.g. `collect_batch`, `structure_section`, `regenerate_section`)
- model name / id
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

**Top-level fields**
- `topic: string` (required)
- `prompt: string | null` (optional)
- `mode: "fast" | "balanced" | "best"` (default: `balanced`)
- `schema_version: string | null`
- `idempotency_key: string | null`
- `constraints: object | null`
- `models: object | null` (NEW; agent model selection)

**constraints**
- `primaryLanguage: "English" | "German" | "Urdu"`
- `learnerLevel: "Newbie" | "Beginner" | "Intermediate" | "Expert" | null`
- `depth: "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "10" | null` (NEW; total number of sections)

> NOTE: `depth` is intentionally an enum (not integer min/max) to keep downstream LLM JSON Schema constraints simple.

**models (agent routing)**
- `knowledge_model: string` (enum; default: `gemini-2.5-flash`)
  - Gemini options: `gemini-2.5-flash`, `gemini-2.5-pro`
  - OpenRouter options: `xiaomi/mimo-v2-flash:free`, `deepseek/deepseek-r1-0528:free`, `openai/gpt-oss-120b:free`
- `structurer_model: string` (enum; default: `gemini-2.5-flash`)
  - Gemini options: `gemini-2.5-flash`
  - OpenRouter options: `openai/gpt-oss-20b:free`, `meta-llama/llama-3.3-70b-instruct:free`, `google/gemma-3-27b-it:free`

Agent 3 (Checker/Repairer) and Agent 4 (Stitcher) are deterministic code and do not accept model parameters.

### Provider integration requirements (DGS)

DGS must support calling Gemini directly and OpenRouter via its OpenAI-compatible chat endpoint.

References:
- OpenRouter quickstart: https://openrouter.ai/docs/quickstart
- Gemini structured outputs: https://ai.google.dev/gemini-api/docs/structured-output

#### OpenRouter (reference request)

- Endpoint: `POST https://openrouter.ai/api/v1/chat/completions`
- Auth: `Authorization: Bearer <OPENROUTER_API_KEY>`
- Optional attribution headers:
  - `HTTP-Referer: <YOUR_SITE_URL>`
  - `X-Title: <YOUR_SITE_NAME>`

Python (requests) example:

```py
import requests
import json

resp = requests.post(
  url="https://openrouter.ai/api/v1/chat/completions",
  headers={
    "Authorization": "Bearer <OPENROUTER_API_KEY>",
    "HTTP-Referer": "<YOUR_SITE_URL>",  # optional
    "X-Title": "<YOUR_SITE_NAME>",      # optional
  },
  data=json.dumps({
    "model": "openai/gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
  }),
)
```

#### Gemini (Google GenAI SDK) structured output (reference)

When Agent 2 uses Gemini, DGS should use native structured outputs by providing `response_mime_type` and `response_json_schema`.

Python example:

```py
from google import genai

client = genai.Client()
response = client.models.generate_content(
  model="gemini-2.5-flash",
  contents="...",
  config={
    "response_mime_type": "application/json",
    "response_json_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
  },
)
json_text = response.text
```

> In production, `response_json_schema` must be the JSON Schema for your lesson/section objects (derived from `widgets.md` / pydantic models).

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
