# Security Best Practices Review Report (FastAPI / Python)

## Executive summary

I reviewed the current uncommitted `git diff` for Dylen Engine (FastAPI + async SQLAlchemy + Cloud Tasks/local task dispatch). The quota/tier work is generally **secure-by-default** (explicit feature gating, hard quotas with transactional counters, and reduced reliance on legacy quota tables). The main risks are around **internal task/worker endpoints** and **information disclosure** in internal responses and user-visible job logs.

This report prioritizes issues by exploitability and impact if the service is exposed to the public internet or to untrusted networks.

---

## Critical findings

### [C-001] Internal task endpoint auth is optional (can allow arbitrary job execution if misconfigured)

- **Severity:** Critical
- **Location:** `app/api/routes/tasks.py:20` (`process_job_task`)
- **Evidence:**
  - Auth check is conditional:
    - `app/api/routes/tasks.py:27-31` only rejects when `settings.task_secret` is set.
  - Otherwise the endpoint processes arbitrary `job_id`:
    - `app/api/routes/tasks.py:33-36`
- **Impact:** If `/internal/tasks/process-job` is reachable and `DYLEN_TASK_SECRET` is unset, an attacker can trigger internal job processing by submitting arbitrary `job_id` values, potentially causing compute/cost abuse, forcing processing of other users’ jobs, or triggering privileged maintenance work depending on job types.
- **Fix (recommended):**
  1) Make internal task endpoints **deny-by-default** by requiring auth *always* in non-local environments (or whenever `task_service_provider == "gcp"`).
  2) Support **one** of:
     - Shared secret (`DYLEN_TASK_SECRET`) validated with constant-time compare, or
     - Verified Cloud Tasks/Cloud Run OIDC (infra-level verification + optional additional audience/issuer validation in-app if you do not fully trust infra routing).
- **Mitigation (defense-in-depth):**
  - Restrict routing so `/internal/*` is not publicly reachable (ingress allowlist / Cloud Run IAM / internal load balancer).
  - Rate limit internal routes at the edge.

### [C-002] Internal lesson worker endpoint auth is optional (same class of risk as C-001)

- **Severity:** Critical
- **Location:** `app/api/routes/worker.py:32` (`process_lesson_endpoint`)
- **Evidence:**
  - Auth check is conditional:
    - `app/api/routes/worker.py:35-39`
  - Endpoint triggers expensive lesson generation work:
    - `app/api/routes/worker.py:79-83`
- **Impact:** If `/worker/process-lesson` is reachable and `DYLEN_TASK_SECRET` is unset, an attacker can trigger lesson generation processing, causing cost/DoS and potential cross-user interference via guessed `job_id`s.
- **Fix (recommended):** Same as C-001: deny-by-default for internal endpoints; require secret/OIDC in production.

---

## High findings

### [H-001] Internal worker endpoint returns raw exception details to the caller (information disclosure)

- **Severity:** High
- **Location:** `app/api/routes/worker.py:93`
- **Evidence:**
  - Returns exception string:
    - `app/api/routes/worker.py:96`
- **Impact:** If the worker endpoint is exposed (even accidentally), exception details may reveal internal IDs, database/infra state, or other sensitive implementation info useful for targeted attacks.
- **Fix (recommended):**
  - Return a generic error payload (e.g., `{"status": "error"}`) and log the detailed exception server-side only.
  - Treat internal endpoints as untrusted network inputs (because “internal-only routing” is frequently misconfigured during deployments).

### [H-002] User-visible job logs may leak internal exception messages

- **Severity:** High
- **Location(s):**
  - `app/api/routes/lessons.py:191-199` (enqueue failure writes `Enqueue failed: {e!s}` into job logs)
  - `app/api/routes/writing.py:100-110` (same pattern)
- **Evidence:**
  - Lesson route:
    - `app/api/routes/lessons.py:198`
  - Writing route:
    - `app/api/routes/writing.py:107`
- **Impact:** If job logs are returned to users (typical for async job polling), raw exception strings can leak internal hostnames, task queue identifiers, provider errors, or other operational details.
- **Fix (recommended):**
  - Store a user-safe error code/message in job logs (e.g., `"Enqueue failed: TASK_ENQUEUE_FAILED"`), while logging full exceptions only to server logs.

---

## Medium findings

### [M-001] Partial user content is written to audit logs (privacy/PII risk)

- **Severity:** Medium
- **Location:** `app/api/routes/writing.py:43-44`
- **Evidence:**
  - `prompt_summary=f"Writing check for: {request.text[:50]}..."`
- **Impact:** Writing checks often contain sensitive or personal content. Storing even a short prefix can create compliance and privacy risk, and it increases blast radius if logs are accessed.
- **Fix (recommended):**
  - Replace with a non-content summary (length, hash, request id), or redact aggressively (e.g., store only `"Writing check queued"`).
  - If you must store content snippets for debugging, gate it behind an operator-only config and ensure logs are access-controlled and retained minimally.

### [M-002] Task secret comparison is not constant-time

- **Severity:** Medium
- **Location:** `app/api/routes/tasks.py:27-31`, `app/api/routes/worker.py:35-39`
- **Evidence:**
  - Uses `authorization != expected`.
- **Impact:** In practice, network jitter usually dominates, but constant-time compares are a low-cost hardening measure for secret comparisons.
- **Fix (recommended):**
  - Use `secrets.compare_digest(authorization or "", expected)` when comparing bearer strings.

---

## Low findings / notes

### [L-001] Cloud Tasks enqueuer includes `Authorization` header when `task_secret` is set (good), but ensure no secret logging

- **Severity:** Low
- **Location:** `app/services/tasks/gcp.py:28-36` and `app/services/tasks/gcp.py:60-64`
- **Evidence:**
  - Adds `authorization` header when `task_secret` exists.
- **Notes:** This is a good step for shared-secret auth parity between local simulation and Cloud Tasks. Ensure request/headers are not logged by proxies/load balancers and that the secret is rotated.

---

## Positive security notes (what’s good in the diff)

- **Feature gating is deny-by-default** (missing flags treated as disabled via `require_feature_flag`), reducing accidental exposure of paid features.
- **Quota counters are transactional** with row locking to reduce race conditions (`app/services/quota_buckets.py:77-103`).
- **Local task dispatch disables environment proxies** (`trust_env=False` in `app/services/tasks/local.py`), reducing accidental proxy interception/SSRF via env vars.

---

## Suggested next hardening steps (small, high value)

1) Make `/internal/*` and `/worker/*` **unreachable from the public internet** by default at the infra layer; treat app-level secrets as defense-in-depth.
2) Enforce “deny-by-default” in app config:
   - If `task_service_provider == "gcp"` (or any non-local mode), require `DYLEN_TASK_SECRET` or verified OIDC configuration at startup.
3) Remove raw exception strings from user-visible job logs and internal HTTP responses.

