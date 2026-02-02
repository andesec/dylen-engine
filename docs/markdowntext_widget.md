# FastAPI Backend Specs — MarkdownText Cutover

## Goal

Replace all non-interactive text/formatting widgets in lesson output with a single widget: `MarkdownText`.

This is a **hard cutover** (development phase): remove the old widget types entirely and stop emitting them.

## Widgets to remove (backend must never emit)

- `paragraph`
- `callouts`
- `warn`
- `success`
- `info`
- `ol`
- `ul`
- `error`
- `warning`

## New widget

### Name

- `MarkdownText`

### Payload contract

- `md: string` (required)
- `align: 'left' | 'center'` (optional)

### Shorthand JSON shape

Use the shortest widget representation your backend currently supports.

**Newline rule (strict):** inside `md` strings, newlines must be encoded as literal `\\n` (do not embed actual line breaks in the JSON string value).

Examples:

```json
["MarkdownText", {"md":"**Hello**\\n\\n- one\\n- two"}]
```

```json
["MarkdownText", {"md":"## Note\\nThis is centered.", "align":"center"}]
```

## Backend requirements for the coding agent

### 1) Research the current backend patterns (mandatory)

Before changes, inspect the repo and document (briefly, in PR description):

- Where widget types are defined (constants/enums, schemas, registries).
- The canonical lesson JSON structure and where it’s assembled.
- Where widget validation happens (pydantic models, custom validators, jsonschema, etc.).
- How these legacy widgets are currently produced (planner/structurer/templating steps, post-processors, repairer loops).
- How lesson JSON is stored/served (DB columns, serialization, response models).

### 2) Update lesson/widget schema in the backend

- Add `MarkdownText` to the allowed widget set.
- Remove all legacy widget definitions from:
  - validation models/logic
  - any schema emitters
  - any widget registries/lists used by generation or repair

### 3) Update all generators and post-processors to emit `MarkdownText`

Replace every place that currently emits any removed widget type.

#### Mapping guidance (generation-time only)

- Emit `MarkdownText` for **all** non-interactive text content.
- Convert stray lines of text in JSON to MarkdownText widget automatically during the repair phase by the Repairer agent.

### 4) Enforce the newline rule (`\\n`) in emitted JSON

- Normalize markdown right before storing/returning JSON:
  - internal representation may use real newlines
  - serialized JSON must contain escaped newlines (`\\n`)

### 5) Strict rejection of legacy widget types

No backward compatibility:

- If the backend receives input containing any removed widget type (fixtures, old DB rows, client payloads), choose one:
  - reject with a clear 400 validation error naming the unsupported widget type, OR
  - fail fast in internal generation pipelines (raise and mark job failed)

Match existing error-handling patterns.

### 6) Update stored examples, fixtures, and seed data

- Replace any JSON fixtures/sample lessons that use legacy widget types.
- Search the repo for the removed widget names and eliminate all occurrences.

### 7)  Tests (minimum)

- Unit tests:
  - `MarkdownText` validation accepts the shorthand shape.
  - Legacy widget types are rejected.
  - Newline normalization outputs `\\n` (not literal newlines) in serialized JSON.
- Integration test (if present):
  - end-to-end generation emits only `MarkdownText` for text-only sections.

## Acceptance criteria

- Backend emits **only** `MarkdownText` for text/formatting content.
- No legacy widget types exist in backend schemas, validators, registries, fixtures, or outputs.
- All markdown strings comply with the strict `\\n` newline rule at serialization time.
- API responses remain valid and consistent with the current response envelope.

