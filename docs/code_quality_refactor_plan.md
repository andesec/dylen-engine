# Code Quality Audit & Refactoring Plan

**Date:** January 26, 2026
**Scope:** `dgs-backend/app`
**Focus:** FastAPI Design, SOLID Principles, OOD, AppSec, AGENTS.md Compliance

---

## Executive Summary

A code review of the `dgs-backend` has identified several opportunities to improve code maintainability, security, and architectural strictness. The following developer stories outline the specific tasks required to address these issues.

---

## Developer Stories

### 1. Refactor Jobs Route Logic to Service Layer

**Context:**
Currently, the `dgs-backend/app/api/routes/jobs.py` file contains significant business logic, specifically within the `create_job_record` function and the `_process_job_async` helper. This violates the Single Responsibility Principle (SRP) by mixing HTTP transport concerns (FastAPI routes) with domain logic (database operations, job scheduling).

**Issue:**
- `jobs.py` handles both request parsing and complex job creation logic.
- Testing the job creation logic independently of the HTTP layer is difficult.

**Proposed Fix:**
- Create a new service module: `app/services/job_service.py` (or extend an existing one if appropriate).
- Move `create_job_record` and logic related to job lifecycle management into this service.
- Update `jobs.py` to inject this service as a dependency and call it.

**Acceptance Criteria:**
- [ ] `create_job_record` is moved from `app/api/routes/jobs.py` to `app/services/jobs.py` (or similar).
- [ ] The `create_job` route handler in `jobs.py` only handles request validation and calling the service.
- [ ] No database models (`JobRecord`) are directly instantiated in the route handler.
- [ ] Unit tests are added or updated to verify the logic in the new service method.

---

### 2. Decompose Orchestrator Monolith

**Context:**
The `DGSOrchestrator` class in `app/ai/orchestrator.py` acts as a "God Object." The `generate_lesson` method is approximately 200 lines long and handles agent coordination, error handling, logging, progress reporting, artifact management, and cost calculation.

**Issue:**
- High complexity makes the code hard to read, test, and maintain.
- Violation of SRP: The orchestrator handles *how* to log and *how* to calculate costs, rather than just coordinating the flow.

**Proposed Fix:**
- Extract specific responsibilities into helper classes or functions:
    - **Progress Management:** Encapsulate `_report_progress` and `_section_progress` logic.
    - **Cost Calculation:** Move `_calculate_total_cost` to a utility or dedicated domain object.
    - **Artifact Management:** Encapsulate the logic for building snapshots and artifacts.

**Acceptance Criteria:**
- [ ] `generate_lesson` method size is significantly reduced (target < 100 lines).
- [ ] Cost calculation logic is isolated in a separate function/method.
- [ ] Progress reporting logic is abstracted or simplified within the main flow.
- [ ] The `DGSOrchestrator` remains responsible only for the high-level flow of agent execution.

---

### 3. Secure Logging Practices (PII Removal)

**Context:**
The `app/api/routes/auth.py` file logs user information upon successful login/signup, including email addresses.

**Issue:**
- Logging PII (Personally Identifiable Information) violates "Secure-by-default" principles and potentially data privacy regulations (GDPR/CCPA).

**Proposed Fix:**
- Audit `auth.py` and other route handlers for PII in log statements.
- Replace direct PII logging with:
    - User IDs (UUIDs).
    - Masked data (e.g., `e***@example.com`).
    - Or removal of the log field entirely if not strictly necessary for debugging.

**Acceptance Criteria:**
- [ ] `app/api/routes/auth.py` no longer logs cleartext email addresses.
- [ ] Log statements use User ID or generic success messages.
- [ ] A quick search of the codebase confirms no other obvious PII logging in route handlers.

---

### 4. Resolve Circular Dependencies in Job Processing

**Context:**
In `app/api/routes/jobs.py`, the function `_process_job_async` imports `JobProcessor` locally (`from app.jobs.worker import JobProcessor`) to avoid top-level import errors.

**Issue:**
- Local imports to avoid circular dependencies are a code smell indicating tight coupling or poor module structure.

**Proposed Fix:**
- Analyze the dependency graph between `api/routes/jobs.py` and `jobs/worker.py`.
- Refactor the shared logic (likely the database/job record definitions) so that `JobProcessor` can be imported at the top level without causing a cycle, OR move the async processing trigger to the service layer created in Story #1.

**Acceptance Criteria:**
- [ ] The local import of `JobProcessor` inside `_process_job_async` is removed.
- [ ] `JobProcessor` is imported at the top level of the file (or the file where the logic resides).
- [ ] The application starts without `ImportError`.

---

### 5. Review CORS and Dev Key Security

**Context:**
`app/config.py` and `app/main.py` configure CORS to explicitly allow the `x-dgs-dev-key` header.

**Issue:**
- If this key is a sensitive administrative secret, exposing it in client-facing CORS headers is a security risk (Security via Obscurity). It suggests clients might be expected to send it.

**Proposed Fix:**
- Confirm the intended use case of `x-dgs-dev-key`.
- If it is for server-to-server or internal admin tools only, ensure it is not required/allowed for standard frontend client requests.
- If it is maintained, add comments explaining the security model.

**Acceptance Criteria:**
- [ ] Usage of `x-dgs-dev-key` is verified.
- [ ] If confirmed as sensitive/internal-only, it is removed from the default CORS allowed headers OR documentation is added justifying its presence.
