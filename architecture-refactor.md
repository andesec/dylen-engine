# Refactoring Specs: DGS Pipeline Architecture

## Goals

- Make the codebase **modular, testable, and provider-agnostic**.
- Separate concerns: **AI calls**, **schema/validation**, **repair**, **stitching**, **persistence**, **progress reporting**.
- Remove provider quirks from business logic.
- Ensure async correctness (no blocking SDK calls on the event loop).

## Non-goals

- Rewriting the entire system in one go.
- Changing product behavior beyond improving reliability and maintainability.

---

## Target Architecture Overview

### Core components

1. **Agents**

   - `PlannerAgent` (creates a section-by-section lesson plan using blueprint + teaching style + learner level)
   - `GathererAgent` (collects raw content **per planned section**)
   - `StructurerAgent` (produces structured lesson JSON **one section at a time**)
   - `RepairerAgent` (always runs after structuring; fixes malformed/invalid JSON)
   - `StitcherAgent` (merges validated sections into final lesson)

2. **Services**

   - `DynamoDbRepository` (job + results persistence)
   - `ProgressTracker` (status updates, phases, telemetry)
   - `SchemaService` (schema load, provider sanitization, validation)
   - `CostTracker` (token accounting and cost per call)

3. **Providers**

   - Provider adapters implementing a clean interface (`GeminiProvider`, `OpenRouterProvider`, etc.)
   - Centralized retry/timeouts/policy wrapper
   - Centralized capability discovery/config

---

## Module Layout (Proposed)

```
app/
  ai/
    agents/
      base.py
      planner.py
      gatherer.py
      structurer.py
      repairer.py
      stitcher.py
    providers/
      base.py
      gemini.py
      openrouter.py
      policy.py
      capabilities.py
    pipeline/
      orchestrator.py
      contracts.py
  schema/
    service.py
    widgets_loader.py
    sanitize.py
    validate.py
  persistence/
    dynamodb.py
    models.py
  progress/
    tracker.py
    events.py
  telemetry/
    cost.py
    logging.py
  api/
    router.py
```

---

## Contracts and Data Models

### Shared contracts (`app/ai/pipeline/contracts.py`)

Define **explicit** dataclasses/pydantic models for:

- `GenerationRequest` (topic, prompt, depth, blueprint, teaching style, language, learnerLevel, etc.)
- `JobContext` (job\_id, timestamps, provider/model, request config)
- `LessonPlan` (topic + ordered `PlanSection[]` + metadata)
- `PlanSection` (section\_number, title, subsections[], planned widgets, per-section gather prompt, section goals)
- `SectionDraft` (section\_number, title, raw\_text, extracted\_parts)
- `StructuredSection` (section\_number, json, validation\_result)
- `RepairResult` (section\_number, fixed\_json, changes, errors)
- `FinalLesson` (lesson\_json, metadata)

**Rule:** Agents accept/return these models only. No dict soup.

---

## Agents

### Base Agent Class

**File:** `app/ai/agents/base.py`

Responsibilities:

- Enforce a consistent lifecycle and interface.
- Own provider handle + cost tracker + schema service + progress tracker (injected).
- Provide common helpers: prompt building, safe logging, retry wrapper.

Interface:

- `name: str`
- `async run(input: Model, ctx: JobContext) -> OutputModel`

---

### PlannerAgent

**Purpose:** Produce an explicit lesson plan before any content generation.

Responsibilities:

- Use **Blueprint** (learning outcome) and **Teaching Style / Implementation** (teaching route) to select the lesson structure.
- Produce `LessonPlan` with:
  - Section titles + subsections
  - Widget suggestions per subsection
  - Per-section **gather prompt** (what content to collect)
  - Continuity rules (what was already covered, what must come next)
- Enforce depth rules exactly (2/6/10 sections).

---

### GathererAgent

**Purpose:** Produce raw learning content **per planned section**.

Responsibilities:

- Input: `PlanSection` + brief context of previously covered sections.
- Call the knowledge model to collect content for **this section only**.
- Output: `SectionDraft`.
- No schema validation here.

---

### StructurerAgent

**Purpose:** Convert a `SectionDraft` to a `StructuredSection`.

Responsibilities:

- Provide structured output request to provider.
- Validate output against schema via `SchemaService`.
- Return `StructuredSection` with validation report.

---

### RepairerAgent

**Purpose:** Fix invalid JSON sections.

Responsibilities:

- Decide if deterministic fix applies.
- If not, call AI repair with strict constraints (section-only, minimal context).
- Re-validate after repair.
- Return `RepairResult` + final validity.

---

### StitcherAgent

**Purpose:** Merge validated sections into final lesson JSON.

Responsibilities:

- Ordering, dedup, stitching rules.
- Final whole-document validation.
- Return `FinalLesson`.

---

## Pipeline Orchestrator

### Responsibilities

**File:** `app/ai/pipeline/orchestrator.py`

- Create `JobContext`
- Run agents in fixed order:
  1. `PlannerAgent` → 2) `GathererAgent` (per section) → 3) `StructurerAgent` (per section) → 4) `RepairerAgent` (per section, always) → 5) `StitcherAgent`
- Persist progress + intermediate artifacts
- Return final result or actionable error

### Depth strategies

Depth is **purely numeric** and determines only the number and type of sections.

- **Highlights (depth = 2)**:

  - Exactly **2 sections**
  - No quiz section

- **Detailed (depth = 6)**:

  - Exactly **6 sections**
  - **Last section is a quiz**

- **Training (depth = 10)**:

  - Exactly **10 sections**
  - **Each section includes a mini quiz**
  - **Final section is a comprehensive exam with swipe, blanks, quiz freetext and console (depending on topic) widgets**

**Invariant rules:**

- `PlannerAgent` must emit exactly `depth` planned sections.
- `GathererAgent` runs **section-by-section** using the planner’s per-section gather prompt.
- `StructurerAgent` always structures **one section at a time**.
- `RepairerAgent` always runs after structuring (no skipping repairs).

### Concurrency

- Use a bounded semaphore (configurable)
- Provider calls must be non-blocking (threadpool if SDK is sync)

---

## Schema Service

### SchemaService

**File:** `app/schema/service.py`

Responsibilities:

- Load widget schema(s) once and cache
- Validate JSON using pydantic/jsonschema
- Return structured validation errors (path + error\_code + message)
- Provider-specific schema sanitization lives here

**Hard rule:** No schema hacks in agents or orchestrator.

---

## Providers

### Provider Base

**File:** `app/ai/providers/base.py`

Methods:

- `async generate_text(prompt, cfg)`
- `async generate_json(prompt, schema, cfg)`

Capabilities:

- `supports_json_schema`
- `max_schema_depth`, `max_enum_size`, etc.

---

## DynamoDB Persistence

### DynamoDbRepository

**File:** `app/persistence/dynamodb.py`

Responsibilities:

- CRUD for jobs and results
- TTL handling
- Conditional updates for progress
- Store blobs directly (no S3)

---

## Progress Tracking

### ProgressTracker

**File:** `app/progress/tracker.py`

Responsibilities:

- Emit structured progress events
- Persist to DynamoDB or forward to DLE
- Stable event schema (phase, step, section\_id, metrics)

---

## Style and Code Hygiene Rules

### Function definitions

**Rule:** Do not split parameters across multiple lines unless the signature exceeds 120 characters.

Allowed:

```python
def generate_structured(prompt: str, schema: dict, model: str, temperature: float) -> dict:
    ...
```

Not allowed:

```python
def generate_structured(
    prompt: str,
    schema: dict,
):
    ...
```

Enforce with `ruff` + `black` (line length 120).

Additional rules:

- No `except Exception` without re-raising a typed error
- No provider/model heuristics outside `capabilities.py`
- No filesystem root discovery via `__file__.parents[...]`

---

## Refactor Plan (Phased)

### Phase 1: Stabilize Interfaces

- Introduce contracts and SchemaService
- Provider base + policy wrapper
- ProgressTracker and CostTracker scaffolding

### Phase 2: Extract Agents

- Implement Agent base
- Move gather/structure/repair/stitch logic into agents
- Slim orchestrator

### Phase 3: Persistence + Progress

- Add DynamoDbRepository
- Persist section-level and final artifacts

### Phase 4: Concurrency + Reliability

- Async-safe provider calls
- Bounded concurrency
- Path-based deterministic repair

### Phase 5: Testing

- Unit tests per agent
- Schema validation + repair tests
- End-to-end integration test

---

## Acceptance Criteria

- Orchestrator < 400 LOC
- Agents testable in isolation
- Async-safe provider calls
- Centralized schema handling
- Isolated DynamoDB and progress services
- Enforced style rules
- No sensitive prompt/response logging by default
