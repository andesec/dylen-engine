# Security Review Report

**Date:** 2023-10-27
**Target:** `app/` directory
**Reviewer:** Jules

## Executive Summary

This report details the findings of a comprehensive secure code review of the `dylen-engine` application. The review focused on OWASP API Security Top 10 risks. Critical vulnerabilities were identified in the areas of Authorization (BOLA), Authentication, and Data Protection. Immediate remediation is recommended for the high-severity findings.

## Findings Summary

| ID | Severity | OWASP Category | Issue | File |
|----|----------|----------------|-------|------|
| 1 | **High** | API1:2023 Broken Object Level Authorization | Missing ownership checks for Jobs | `app/services/jobs.py` |
| 2 | **High** | API1:2023 Broken Object Level Authorization | Missing ownership checks for Lessons | `app/api/routes/lessons.py` |
| 3 | **High** | API2:2023 Broken Authentication | Unsecured Internal Task Endpoint | `app/api/routes/tasks.py` |
| 4 | **Medium** | API6:2023 Unrestricted Access to Sensitive Business Flows | Blind SSRF via Research Agent | `app/ai/agents/research.py` |
| 5 | **Medium** | API3:2023 Broken Object Property Level Authorization | Sensitive Data Exposure in Logs (Request Body) | `app/core/middleware.py` |
| 6 | **Medium** | API3:2023 Broken Object Property Level Authorization | Sensitive PII Storage in Audit Logs | `app/telemetry/llm_audit.py` |
| 7 | **Low** | API4:2023 Unrestricted Resource Consumption | Missing Length Constraints on Input | `app/api/models.py` |

---

## Detailed Findings

### 1. Missing Ownership Checks for Jobs (BOLA)

**Severity:** High
**OWASP:** API1:2023 Broken Object Level Authorization

**Description:**
The `get_job_status` function retrieves job details using only the `job_id`. It does not verify that the requesting user owns the job. Any authenticated user (or anyone with access to the endpoint) can view the status and results of any job if they know or guess the UUID.

**Location:**
*   File: `app/services/jobs.py`
*   Function: `get_job_status` (and `retry_job`, `cancel_job`)
*   Lines:
    ```python
    async def get_job_status(job_id: str, settings: Settings) -> JobStatusResponse:
      repo = _get_jobs_repo(settings)
      record = await repo.get_job(job_id)
      # ... returns record without user_id check
    ```

**Remediation:**
1.  Update `JobRecord` (and the underlying `dylen_jobs` table) to explicitly store `user_id` or `org_id` as a top-level column, not just inside `request` metadata.
2.  Update `get_job_status` to accept `user_id` (from `current_user`).
3.  Add a check: `if record.user_id != user_id: raise HTTPException(403)`.

---

### 2. Missing Ownership Checks for Lessons (BOLA)

**Severity:** High
**OWASP:** API1:2023 Broken Object Level Authorization

**Description:**
Similar to jobs, the `get_lesson` endpoint retrieves a lesson by `lesson_id` without verifying ownership. The `LessonRecord` schema does not appear to store the owner's `user_id`.

**Location:**
*   File: `app/api/routes/lessons.py`
*   Endpoint: `GET /{lesson_id}`
*   Lines:
    ```python
    @router.get("/{lesson_id}", ...)
    async def get_lesson(lesson_id: str, ...):
      repo = _get_repo(settings)
      record = await repo.get_lesson(lesson_id)
      # ... returns record
    ```

**Remediation:**
1.  Add `user_id` and `org_id` columns to the `dylen_lessons` table and `LessonRecord`.
2.  Enforce ownership checks in the `get_lesson` repository method or the route handler.

---

### 3. Unsecured Internal Task Endpoint (Broken Authentication)

**Severity:** High
**OWASP:** API2:2023 Broken Authentication / API7:2023 Server Side Request Forgery (SSRF) Target

**Description:**
The `/tasks/process-job` endpoint is designed for Cloud Tasks but lacks any authentication verification. It relies solely on network perimeter security (which may be bypassed or misconfigured). The code contains a TODO: `# TODO: Verify OIDC token or internal secret here.`

**Location:**
*   File: `app/api/routes/tasks.py`
*   Endpoint: `POST /process-job`
*   Lines:
    ```python
    @router.post("/process-job", status_code=status.HTTP_200_OK)
    async def process_job_task(payload: TaskPayload, ...):
      # TODO: Verify OIDC token or internal secret here.
      await process_job_sync(payload.job_id, settings)
    ```

**Remediation:**
1.  Implement OIDC token verification for Cloud Tasks (verify the token was issued by Google for the expected service account).
2.  Alternatively, use a shared secret (API Key) stored in environment variables if OIDC is too complex for the current stage.

---

### 4. Blind SSRF via Research Agent

**Severity:** Medium
**OWASP:** API6:2023 Unrestricted Access to Sensitive Business Flows / API7:2023 SSRF

**Description:**
The `ResearchAgent` allows the system to fetch arbitrary URLs provided by the user via the `TavilyProvider`. While this uses an external proxy (Tavily), it still allows users to use the application to retrieve content from the web, potentially bypassing client-side restrictions or masking the user's IP.

**Location:**
*   File: `app/ai/agents/research.py`
*   Method: `_crawl_urls` calling `_fetch_content_tavily`
*   Lines:
    ```python
    response = await self.tavily_provider.search(query=url, ...)
    ```

**Remediation:**
1.  Validate input URLs against a blocklist/allowlist if possible.
2.  If the feature is intended to crawl *any* URL, ensure the `ResearchAgent` cannot be abused to fetch internal or sensitive external endpoints (e.g. cloud metadata services, though Tavily likely blocks these).
3.  Implement rate limiting on this specific feature.

---

### 5. Sensitive Data Exposure in Logs (Request Body)

**Severity:** Medium
**OWASP:** API8:2023 Security Misconfiguration / Sensitive Data Exposure

**Description:**
The `RequestLoggingMiddleware` logs the full body of JSON requests when `debug` logging is enabled (which might occur in non-prod or via accidental config). This includes login requests with `idToken` or other credentials.

**Location:**
*   File: `app/core/middleware.py`
*   Lines:
    ```python
    if content_type.startswith("application/json") and body:
      logger.debug(f"Request Body: {body.decode('utf-8')}")
    ```

**Remediation:**
1.  Implement a redaction filter that masks keys like `token`, `password`, `key`, `authorization` in the logged JSON.
2.  Alternatively, disable body logging for specific sensitive routes (like `/api/auth/login`).

---

### 6. Sensitive PII Storage in Audit Logs

**Severity:** Medium
**OWASP:** API8:2023 Security Misconfiguration / Sensitive Data Exposure

**Description:**
The `LLMAuditLog` mechanism stores the full `request_payload` and `response_payload` in the database. If users include PII (names, emails, health info) in their prompts, this data is persisted permanently in the audit logs, complicating GDPR compliance (Right to Erasure).

**Location:**
*   File: `app/telemetry/llm_audit.py`
*   Function: `start_llm_call`

**Remediation:**
1.  Implement a PII scrubber before logging payloads.
2.  Or, implement a strictly shorter retention policy for audit logs.
3.  Encrypt the payload columns in the database.

---

### 7. Missing Length Constraints on Input

**Severity:** Low
**OWASP:** API4:2023 Unrestricted Resource Consumption

**Description:**
The `GenerateLessonRequest` model has a `details` field with a description stating "max 250 words", but there is no programmatic enforcement of this length in the Pydantic model (only `min_length=1`).

**Location:**
*   File: `app/api/models.py`
*   Line:
    ```python
    details: StrictStr | None = Field(default=None, min_length=1, description="Optional user-supplied details (max 250 words).", ...)
    ```

**Remediation:**
1.  Add `max_length` to the `Field` definition (e.g., `max_length=2000` characters approx for 250 words).
