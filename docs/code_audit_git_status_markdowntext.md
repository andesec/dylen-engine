## Code Review + Audit (git status): MarkdownText cutover

Date: 2026-02-02

Scope: All files currently modified/untracked in `git status` related to the MarkdownText (`markdown`) cutover.

### High-level verification

- Schema now enforces `MarkdownText` as the only non-interactive text widget using `{"markdown":[md, align?]}`. (`app/schema/lesson_models.py:31`, `app/schema/lesson_models.py:705`)
- Job pipeline validates the merged lesson payload and fails fast when invalid (so invalid/legacy widgets should not persist or be returned as a successful result). (`app/jobs/worker.py:276`)
- Repair/conversion layers attempt to normalize legacy text shapes into `markdown` before validation. (`app/ai/agents/stitcher.py:42`, `app/ai/deterministic_repair.py:166`)

### Findings

#### 1) Output hardening: legacy shorthand edge cases now normalized, but multi-key legacy objects can still leak into intermediate payloads

- Rule ID: DLE-WIDGETS-001
- Severity: Medium
- Location: `app/ai/agents/stitcher.py:53`
- Evidence:
  - Stitcher converts removed shorthand widgets only when the object has exactly one key (e.g. `{"p":"..."}`, `{"warn":"..."}`, `{"ul":[...]}`) and leaves multi-key objects untouched. (`app/ai/agents/stitcher.py:54`)
- Impact:
  - If upstream emits `{"p":"...", "meta":...}` or `{"warn":"...", "title":...}` (no `type`), Stitcher will pass it through. That will fail schema validation later and cause job failure rather than graceful normalization.
- Recommendation:
  - Consider hardening `_convert_item` to detect removed keys even in multi-key dicts and either:
    - fold into `markdown` while preserving extra fields in a safe way (e.g., append a `- meta: ...` block), or
    - fail fast immediately with a clear error pointing at the unsupported widget key.

#### 2) Contract strictness: `markdown` requires a list, but list elements are still coerced to `str`

- Rule ID: DLE-WIDGETS-002
- Severity: Low
- Location: `app/schema/lesson_models.py:46`
- Evidence:
  - The validator enforces list shape, but coerces list entries via `str(...)`. (`app/schema/lesson_models.py:48`)
- Impact:
  - Type confusion is possible (e.g., `{"markdown":[123]}` becomes `"123"`), which may hide upstream bugs and make payloads less predictable.
- Recommendation:
  - If you want strictness, reject non-`str` values instead of coercing. Keep coercion only if resilience is preferred.

#### 3) Spec alignment: fail-fast behavior is implemented in the job pipeline, not via 400 HTTP validation

- Rule ID: DLE-WIDGETS-003
- Severity: Low
- Location: `app/jobs/worker.py:276`
- Evidence:
  - Worker validates and raises on validation failure (`ValueError`), preventing success writes. (`app/jobs/worker.py:280`)
- Impact:
  - This matches the “fail fast in internal generation pipelines” option from the spec, but it means client-side payload validation (400) is not the enforcement mechanism.
- Recommendation:
  - Ensure any public endpoint that accepts lesson JSON uses the same schema validation and returns a 400 (if/when such an endpoint exists).

#### 4) Security (defense-in-depth): Markdown rendering XSS risk is downstream-dependent

- Rule ID: FASTAPI-XSS-001
- Severity: Medium (could be High depending on renderer)
- Location: `app/schema/lesson_models.py:31`
- Evidence:
  - `md` accepts arbitrary user/LLM-provided content and can include links and (depending on renderer) raw HTML.
- Impact:
  - If a client renders Markdown with raw HTML enabled and without sanitization, this can become an XSS vector.
- Recommendation:
  - Ensure the renderer sanitizes output and disables raw HTML in Markdown unless explicitly needed.
  - If the server ever renders Markdown to HTML, require sanitization and consider an allowlist of tags/attributes.

#### 5) Reliability: deterministic repair now supports `paragraph` / `callouts` shorthand keys as additional legacy aliases

- Rule ID: DLE-WIDGETS-004
- Severity: Low
- Location: `app/ai/deterministic_repair.py:178`
- Evidence:
  - `paragraph`/`callouts` are included in legacy normalization and converted to `markdown`. (`app/ai/deterministic_repair.py:178`, `app/ai/deterministic_repair.py:226`)
- Impact:
  - Improves success rate when upstream emits these spec-listed legacy widget names in shorthand form.
- Recommendation:
  - None required.

#### 6) Documentation correctness: widgets docs no longer advertise removed widgets, but full-form `type` “escape hatch” is still described

- Rule ID: DLE-DOCS-001
- Severity: Low
- Location: `app/schema/widgets_prompt.md:1`, `app/schema/widgets.md:1`, `samples/structurer_prompt.md:1`
- Evidence:
  - Docs still mention a full-form object with `type`, while schema is shorthand-driven and relies on Stitcher conversion for any full-form inputs.
- Impact:
  - Minor drift could confuse LLM prompting and human authors.
- Recommendation:
  - If full-form is not intended to be accepted at the schema boundary, clarify that full-form is tolerated only as an intermediate input and must be converted to shorthand before validation.

### Test status

- Targeted tests covering `markdown` shorthand acceptance, legacy rejection, and newline serialization pass:
  - `tests/unit/test_markdowntext_widget.py:1`
  - `tests/unit/test_widgets_loader.py:1`
- Full test suite currently fails collection due to missing `brotli` (environment/dependency issue unrelated to this change).

