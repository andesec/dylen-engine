## Security + Implementation Review: MarkdownText Cutover

Scope: Verification of `docs/markdowntext_widget.md` against the current implementation, with a security-focused review of the new `MarkdownText` (`markdown`) widget in the FastAPI backend.

### Summary

The backend now enforces `MarkdownText` as the only non-interactive text/formatting widget using the shorthand `{"markdown": [md, align?]}`. Legacy text widgets and string-based paragraphs are rejected by schema validation, and internal pipeline components convert legacy shapes into `markdown` before validation.

### Findings

#### 1) Spec alignment: `markdown` shorthand is enforced by schema validation

- Severity: Low
- Location: `app/schema/lesson_models.py:31`
- Evidence:
  - `MarkdownTextWidget.markdown` requires a list payload and enforces `[md, align?]` with `align` limited to `"left"`/`"center"`. (`app/schema/lesson_models.py:44`)
  - The global `Widget` union no longer accepts raw strings (paragraph shorthand) and no longer includes `p/warn/success/ul/ol` widget models. (`app/schema/lesson_models.py:706`)
- Impact:
  - Any payload containing removed widgets or raw string items fails validation (matching the “hard cutover” requirement).
- Fix:
  - None required.

#### 2) Strict shorthand enforcement: non-array `markdown` payloads are rejected

- Severity: Low
- Location: `app/schema/lesson_models.py:46`
- Evidence:
  - `validate_markdown_pre` rejects any non-list `markdown` values. (`app/schema/lesson_models.py:48`)
  - Unit tests cover rejecting `{"markdown":"..."}` and `{"markdown":{"md":"..."}}`. (`tests/unit/test_markdowntext_widget.py:14`)
- Impact:
  - Prevents silent acceptance of non-contract payloads and keeps repair responsibilities clear.
- Fix:
  - None required.

#### 3) Legacy widget names still exist in code paths (conversion/normalization)

- Severity: Low
- Location:
  - `app/ai/agents/stitcher.py:54`
  - `app/ai/deterministic_repair.py:1`
- Evidence:
  - The Stitcher converts legacy shorthand keys (`p`, `warn`, `err`, `success`, `ul`, `ol`, plus `info/error/warning`) into `markdown`. (`app/ai/agents/stitcher.py:54`)
- Impact:
  - This technically violates a literal reading of “eliminate all occurrences” in `docs/markdowntext_widget.md`, although it does not cause the backend to emit legacy widgets.
- Recommendation:
  - Decide whether “eliminate all occurrences” applies to examples/fixtures/outputs only, or also to internal conversion code. If it applies to code, remove these conversion paths and fail-fast instead.

#### 4) Potential XSS risk if `markdown` is rendered unsafely downstream

- Severity: Medium (could be High depending on renderer)
- Location:
  - `app/schema/lesson_models.py:31` (accepts arbitrary Markdown text)
- Evidence:
  - `md` is untrusted content that can contain links and (depending on client renderer settings) raw HTML.
- Impact:
  - If any consumer renders Markdown to HTML without sanitization, attacker-controlled content could lead to XSS in browsers.
- Recommendation (defense-in-depth):
  - Ensure the renderer sanitizes HTML and disables raw HTML in Markdown unless explicitly needed.
  - If server-side Markdown rendering exists anywhere (not visible in this change set), ensure a sanitizer is applied and consider allowing only a safe subset of Markdown.

#### 5) DoS / payload size considerations for large `md` values

- Severity: Medium
- Location:
  - `app/schema/lesson_models.py:31`
- Evidence:
  - There is currently no maximum length enforcement for `md`.
- Impact:
  - Very large markdown strings can increase memory and CPU usage (validation, transport, storage, rendering), contributing to request-level DoS.
- Recommendation:
  - Add reasonable limits for markdown size at the edge (reverse proxy) and/or at validation time (e.g., a max character length) if this endpoint accepts client-provided lesson payloads.

#### 6) Spec naming mismatch risk: `error`/`warning` vs `err`/`warn`

- Severity: Low
- Location:
  - `docs/markdowntext_widget.md:1`
  - `app/ai/agents/stitcher.py:64`
- Evidence:
  - The spec removal list includes `error`/`warning`, while the prior shorthand schema used `err`/`warn`. The conversion layer checks both. (`app/ai/agents/stitcher.py:64`)
- Impact:
  - Confusion during future maintenance and audits (what is actually “removed”).
- Recommendation:
  - Clarify the canonical removed keys in the spec (e.g., include both aliases or specify exact engine keys).

### Test status

- Targeted unit tests for the new widget pass: `tests/unit/test_markdowntext_widget.py:1`, `tests/unit/test_widgets_loader.py:1`.
- Full test suite currently fails during collection due to a missing `brotli` dependency (unrelated to this widget change).

