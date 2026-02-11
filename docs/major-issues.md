Implemented as a full read-only audit. No files were modified.

**Severity-Ranked Findings**

1. **Critical: Cross-user tutor audio access is possible**
    - Evidence: `app/api/routes/tutor.py:22` queries `TutorAudio` by `job_id` only; `app/api/routes/tutor.py:45` queries by `audio_id` only. Neither joins to job owner or lesson owner.
    - Impact: Any approved user with `tutor:audio_view_own` can potentially access another user’s tutor audio if they know/guess IDs.
    - Remediation: Add ownership join/filter (`job.user_id == current_user.id` or lesson ownership chain) in both endpoints before returning data.

2. **High: Runtime-config key drift (consumed keys not defined/validated/fallbacked)**
    - Evidence: `limits.outcomes_checks_per_week` used at `app/api/routes/lessons.py:118`; `limits.max_outcomes` used at `app/api/routes/lessons.py:137`; neither exists in `_RUNTIME_CONFIG_DEFINITIONS` (`app/services/runtime_config.py:38`).
    - Impact: Operators cannot manage these values via admin runtime-config APIs; behavior is implicit/fallback-only and inconsistent with runtime-config contract.
    - Remediation: Add both keys to `_RUNTIME_CONFIG_DEFINITIONS`, `_validate_value`, `_env_fallback` in `app/services/runtime_config.py`.

3. **High: Job create API accepts targets that worker cannot process**
    - Evidence: `_COMPATIBLE_TARGETS` includes `research`, `writing`, `youtube` in `app/services/jobs.py:23`; worker registry only supports `planner`, `section_builder`, `fenster_builder`, `tutor`, `illustration`, `maintenance` in `app/jobs/worker.py:79`.
    - Impact: Valid accepted API requests can enqueue jobs that later fail at dispatch (`Unsupported target agent` path via `app/jobs/dispatch.py:38`).
    - Remediation: Constrain `create_job` compatibility map to worker-supported targets, or add missing handlers.

4. **High: Approval-status checks are not re-validated in delayed worker execution**
    - Evidence: Worker/task paths hydrate user with `get_user_by_id` only (`app/api/routes/worker.py:71`, `app/jobs/worker.py:174`) and do not enforce `APPROVED`/`is_discarded` checks like `get_current_active_user` (`app/core/security.py:130`).
    - Impact: Jobs queued while approved may still run after user is rejected/discarded; policy drift between synchronous API auth and async execution.
    - Remediation: Add centralized worker-side active-user guard before processing user-scoped jobs.

5. **High: Feature-flag tether drift for image/fenster generation**
    - Evidence: Quota visibility is flag-gated for image generation (`app/services/quotas.py:225` uses `feature.image_generation`), but worker generation path does not evaluate that flag (`app/jobs/worker.py:306`, `app/jobs/worker.py:571`); fenster retrieval route is gated (`app/api/routes/fenster.py:17`) while generation is not flag-gated (`app/jobs/worker.py:320`, `app/jobs/worker.py:424`).
    - Impact: Features can be “disabled” in capability responses while still consuming compute and generating artifacts.
    - Remediation: Enforce relevant feature decisions in generation paths (section child-job creation and/or worker handlers), not just in retrieval or quota summaries.

6. **High: Planner repair logic contains invalid iteration that can raise**
    - Evidence: `_repair_planner_json` loops incorrectly at `app/ai/agents/planner.py:39` (`for _k, v in section[field]:` over a possibly string/list value).
    - Impact: Recovery path for malformed model output may crash, converting recoverable output into hard failure.
    - Remediation: Replace with type-safe normalization logic per field (dict/list/string handling).

7. **Medium: Generic worker handlers ignore runtime-config AI model/provider overrides**
    - Evidence: Planner/section/fenster handlers use settings directly: `app/jobs/worker.py:208`, `app/jobs/worker.py:283`, `app/jobs/worker.py:430`.
    - Impact: Different behavior across processing paths (`/worker/process-lesson` vs `/internal/tasks/process-job`) for same tenant/tier.
    - Remediation: Resolve runtime config per user/tier and use `ai.*` runtime keys consistently in all worker handlers.

8. **Medium: Fenster widget retrieval has no per-user ownership boundary**
    - Evidence: `app/api/routes/fenster.py:28` fetches by `fenster_id` only; schema has no `user_id` (`app/schema/fenster.py:18`).
    - Impact: Any authorized tier user can access any widget ID if discovered.
    - Remediation: Add ownership model (e.g., widget-to-lesson/user linkage) and enforce it in route query.

9. **Medium: Super-admin-only runtime config is exposed in effective-config endpoint**
    - Evidence: `/admin/config/effective` returns full config map directly (`app/api/routes/configuration.py:227`), unlike user-facing features endpoint that redacts super-admin keys (`app/api/routes/users.py:64`).
    - Impact: `super_admin_only` semantics are enforced for writes but not consistently for reads.
    - Remediation: Apply `redact_super_admin_config` or require super-admin for full effective config view.

10. **Low: Verification tooling/tests do not currently guard these drift classes**
    - Evidence: Feature matrix script exists (`scripts/verify_feature_flag_matrix.py:1`), but no equivalent runtime-config key drift verifier; tests reference undefined key (`tests/unit/test_widget_entitlements.py:69`) and no tutor ownership tests were found in `tests`.
    - Impact: Regressions in config/ownership tethers can reappear unnoticed.
    - Remediation: Add static integrity check script for runtime keys and ownership-focused API tests.

---

**Comprehensive Matrix 1: Externally Reachable Entrypoints (Control Coverage)**

| Entrypoint | Auth dependency | RBAC | Feature flag gate | Runtime config usage | Quota enforcement | Ownership enforcement | Idempotency/retry notes | Parity notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `app/api/routes/onboarding.py:17` `/api/me` | `get_current_user_or_provision` | No | No | No | No | Self profile only | N/A | Intentional pre-approval flow |
| `app/api/routes/purgatory.py:14` `/api/purgatory` | `get_current_user` | No | No | No | No | Self role/status only | N/A | Intentional pre-approval flow |
| `app/api/routes/lessons.py:161` `/v1/lessons/generate` | `get_current_active_user` | `lesson:generate` | No | Yes | Yes | User-scoped job/lesson | idempotency key enforced | Uses `/worker/process-lesson` path |
| `app/api/routes/lessons.py:345` `/v1/lessons/jobs` | `get_current_active_user` | `lesson:job_create` | No | Yes (validation) | No pre-check for lesson/section quotas | User-scoped via job service | idempotency via `JobCreateRequest` | Uses generic `/internal/tasks/process-job` path |
| `app/api/routes/jobs.py:17` `/v1/jobs` | `get_current_active_user` | `job:create_own` | No | Indirect | `_ensure_quota_available` | User id attached | idempotency required | Accepts unsupported target sets |
| `app/api/routes/research.py:26` `/v1/research/discover` | `get_current_active_user` | `research:use` | `feature.research` | No | Concurrency only | user_id passed to agent | per-call tracking job | Not processed by generic worker |
| `app/api/routes/writing.py:44` `/v1/writing/check` | `get_current_active_user` | `writing:check` | `feature.writing` | Yes | Reserve/commit/release | Self-scoped | job_id tracking only | Sync path |
| `app/api/routes/resources.py:38` `/resource/image/extract-text` | `get_current_active_user` | `ocr:extract` | `feature.ocr` | Yes | service-enforced OCR quota | Self-scoped | N/A | Sync path |
| `app/api/routes/tutor.py:19` `/v1/tutor/job/{job_id}/audios` | `get_current_active_user` | `tutor:audio_view_own` | No | No | No | **Missing owner filter** | N/A | Data exposure risk |
| `app/api/routes/tutor.py:42` `/v1/tutor/audio/{audio_id}/content` | `get_current_active_user` | `tutor:audio_view_own` | No | No | No | **Missing owner filter** | N/A | Data exposure risk |
| `app/api/routes/fenster.py:17` `/api/v1/fenster/{widget_id}` | active via permission dependency | `fenster:view` + tier | `feature.fenster` | No | No | **No per-user ownership model** | N/A | Retrieval gated; generation not gated |
| `app/api/routes/tasks.py:21` `/internal/tasks/process-job` | task secret only | No | No | Indirect via worker | Indirect | No active-user recheck | async background processing | Generic worker path |
| `app/api/routes/worker.py:33` `/worker/process-lesson` | task secret only | No | No | Indirect via `process_lesson_generation` | Yes (section) + agent reservations | No active-user recheck | idempotent skip for processing/done | Separate legacy worker path |

---

**Comprehensive Matrix 2: Runtime Config Integrity**

| Check | Result | Evidence |
| :--- | :--- | :--- |
| Definitions count | 59 keys | `app/services/runtime_config.py:38` |
| `_env_fallback` coverage vs definitions | 59/59 covered | `app/services/runtime_config.py:165` |
| Used-but-undefined keys | **2 keys** | `app/api/routes/lessons.py:118`, `app/api/routes/lessons.py:137` |
| Missing keys | `limits.outcomes_checks_per_week`, `limits.max_outcomes` | same as above |
| Validation/fallback contract breach for missing keys | Yes | Definitions absent in `app/services/runtime_config.py:38` |

---

**Comprehensive Matrix 3: Feature-Flag Tethers**

| Feature key | Route-level gate | Service/worker gate | Quota/capability surface | Consistency |
| :--- | :--- | :--- | :--- | :--- |
| `feature.research` | Yes (`app/api/routes/research.py:26`) | No worker path | Not bucket-gated in quota entries | Mostly consistent for current sync route |
| `feature.writing` | Yes (`app/api/routes/writing.py:44`) | N/A | Gated in quota summary (`app/services/quotas.py:223`) | Consistent |
| `feature.ocr` | Yes (`app/api/routes/resources.py:38`) | N/A | Gated (`app/services/quotas.py:222`) | Consistent |
| `feature.fenster` | Yes for retrieval (`app/api/routes/fenster.py:17`) | **No for generation** (`app/jobs/worker.py:320`, `app/jobs/worker.py:424`) | Fenster quota entry is not feature-gated (`app/services/quotas.py:221`) | **Inconsistent** |
| `feature.image_generation` | No direct route gate | **No generation gate** (`app/jobs/worker.py:306`, `app/jobs/worker.py:571`) | Gated in quota summary (`app/services/quotas.py:225`) | **Inconsistent** |
| `feature.tutor.mode` | No direct route gate | Yes (`app/jobs/worker.py:518`, `app/ai/orchestrator.py:317`) | Tutor quota independent of mode | Mostly consistent |
| `feature.notifications.email` | No route gate | Service check (`app/services/lessons.py:130`) | N/A | Consistent |
| `feature.youtube_capture`, `feature.mock_exams`, `feature.mock_interviews`, `feature.tutor.active` | No active runtime route found | No active execution path found | Present in quota/capability summaries (`app/services/quotas.py:224`, `app/services/quotas.py:226`, `app/services/quotas.py:227`) | Future-facing; no immediate runtime tether |

---

**Comprehensive Matrix 4: Approval + Ownership Boundaries**

| Area | Status | Evidence |
| :--- | :--- | :--- |
| Protected user routes enforce active approved user | Good | `app/core/security.py:130` |
| Onboarding/purgatory allow pending users intentionally | Good | `app/api/routes/onboarding.py:17`, `app/api/routes/purgatory.py:14` |
| Async worker re-checks active/discarded status | **Missing** | `app/api/routes/worker.py:71`, `app/jobs/worker.py:174` |
| Jobs API ownership checks | Good | `app/services/jobs.py:157`, `app/services/jobs.py:197` |
| Tutor audio ownership checks | **Missing** | `app/api/routes/tutor.py:22`, `app/api/routes/tutor.py:45` |
| Fenster ownership boundary | **Missing model-level tether** | `app/api/routes/fenster.py:28`, `app/schema/fenster.py:18` |

---

**Supporting Scripts/Tests Drift**

| Area | Current state | Gap |
| :--- | :--- | :--- |
| Feature flag matrix verification | Present (`scripts/verify_feature_flag_matrix.py:1`) | Good coverage for DB matrix only |
| Runtime-config key drift verification | Not found | Missing guard for consumed-vs-defined keys |
| Tutor ownership tests | Not found in `tests` search | Missing regression protection |
| Job target compatibility tests | Not found in `tests` search | Missing guard against accepted-but-unhandled targets |

---

**Remediation Recommendations (Ordered)**

1. Lock down tutor ownership in `app/api/routes/tutor.py`.
2. Add runtime-config definitions for `limits.outcomes_checks_per_week` and `limits.max_outcomes`.
3. Align job compatibility map with worker registry or add handlers for `research`/`writing`/`youtube`.
4. Add worker-side active/discarded recheck before any user-scoped execution.
5. Enforce `feature.fenster` and `feature.image_generation` in generation paths, not only retrieval/quota surfaces.
6. Fix `_repair_planner_json` normalization logic.
7. Standardize worker model/provider resolution via runtime config.
8. Add runtime-config drift check script and targeted ownership/dispatch tests.
