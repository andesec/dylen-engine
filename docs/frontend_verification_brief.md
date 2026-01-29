# Frontend Implementation Brief: Dylen API Integration

## Context
Dylen (Engine) acts as a **Backend for Frontend (BFF)** for the Dylen (Frontend). It manages session security and orchestrates calls to LLM providers.
**Crucial**: The Dylen should **not** manage long-lived tokens/secrets. It exchanges a temporary Firebase credential for a secure, HTTP-only session cookie managed by Dylen.

## 1. Authentication Architecture (Current State)
> [!NOTE]
> **PKCE vs Request Exchange**: The user has asked about PKCE.
> Currently, the system implements **ID Token Exchange**. The Frontend performs the OAuth dance (using Firebase SDK), gets an ID Token, and sends it to the Backend. The Backend verifies it and mints a Session Cookie.
> *True PKCE* (where the Backend handles the Redirect) is **not** currently implemented. This document verifies the **existing code**.

### Sequence
1.  **Firebase Login (Frontend)**: User signs in via Firebase SDK (e.g., Google Sign-In).
2.  **Get Token**: Frontend calls `user.getIdToken()` to get the JWT.
3.  **Exchange Token (Dylen)**:
    *   **Endpoint**: `POST /api/auth/login`
    *   **Payload**: `{"idToken": "<FIREBASE_ID_TOKEN>"}` 
        *   *Note: Using `camelCase` key `idToken` is required.*
    *   **Response**: `200 OK` + `Set-Cookie: session=<TOKEN>; HttpOnly; Secure; SameSite=Lax`
4.  **Authenticated Requests**: All subsequent API calls to Dylen **must** include credentials (cookies).
    *   *Frontend Config*: Ensure `withCredentials: true` (axios/fetch) is set globally.

## 2. API Call Sequences & Workflows

### A. Initialization
Call this on app load to populate UI options.
1.  **Get Catalog**: `GET /v1/lessons/catalog`
    *   *Returns*: Available blueprints, teaching styles, and widget definitions.

### B. Lesson Generation (Async Job)
1.  **Start Job**: 
    *   **Endpoint**: `POST /v1/jobs`
    *   **Payload**: `GenerateLessonRequest` (Topic, Blueprint, etc.)
    *   **Response**: `{"job_id": "...", "expected_sections": 5}`
2.  **Poll Progress**:
    *   **Endpoint**: `GET /v1/jobs/{job_id}`
    *   **Frequency**: Poll every ~2-5 seconds.
    *   **Stop Condition**: `status` is `done`, `error`, or `canceled`.
    *   **Partial Updates**: The response includes `progress` (0-100) and `logs` for UI feedback.
3.  **Retrieve Result**:
    *   The final job status response contains the `result` (Lesson JSON).
    *   *Optional*: Retrieve persisted lesson via `GET /v1/lessons/{lesson_id}` (Lesson ID is in the job result).

### C. Writing Check (Async Job)
1.  **Start Check**:
    *   **Endpoint**: `POST /v1/writing/check`
    *   **Payload**: `{"text": "...", "criteria": "..."}`
    *   **Response**: `{"job_id": "..."}`
2.  **Poll Progress**: Same as Lesson Generation (`GET /v1/jobs/{job_id}`).

### D. Admin / Monitoring
*   `GET /admin/jobs`: List background jobs.
*   `GET /admin/lessons`: List generated lessons.
*   `GET /admin/llm-calls`: Audit log of LLM interactions.

## 3. Verification Checklist for Gemini
- [ ] **Login Payload**: Ensure `idToken` key is used (not `id_token`).
- [ ] **Cookie Handling**: Verify browser is receiving and sending the `session` cookie.
- [ ] **API Prefixes**: Ensure client uses `/v1/...` for lessons/jobs/writing and `/admin/...` for admin routes.
- [ ] **Error Handling**: 
    - `401 Unauthorized` -> Redirect to Login.
    - `422 Unprocessable Entity` -> Check payload structure (snake_case vs camelCase).
- [ ] **Job Polling**: Ensure polling stops correctly on terminal states (`done`, `error`).
