# Authentication & LLM Audit Logging Flow

This document describes the secure BFF authentication flow and LLM audit logging mechanism implemented in the DGS service.

## 1. Authentication Flow

The DGS service acts as a Backend-For-Frontend (BFF) and uses a secure session cookie to manage user authentication. The identity provider is Google Firebase Auth.

### 1.1. Login Process

1.  **Frontend**: The client application (Frontend) authenticates the user using the Firebase Client SDK.
    -   This results in a Firebase ID Token.
2.  **Exchange**: The Frontend sends this ID Token to the DGS backend via a POST request to `/api/auth/login`.
    ```json
    POST /api/auth/login
    Content-Type: application/json

    {
      "id_token": "..."
    }
    ```
3.  **Verification (Backend)**:
    -   The DGS backend verifies the ID Token using the Firebase Admin SDK.
    -   It extracts the `uid` and `email` from the token.
    -   It checks if the user exists in the PostgreSQL `users` table.
    -   **Auto-Signup**: If the user does not exist, a new record is created with `is_approved = False`.
    -   **Approval Check**: If `is_approved` is `False`, the backend returns `403 Forbidden`.
4.  **Session Creation**:
    -   If the user is approved, the backend creates a Session Cookie (using Firebase Admin SDK's `create_session_cookie` or similar mechanism).
    -   The cookie is set with the following attributes:
        -   `HttpOnly`: Prevent XSS access.
        -   `Secure`: HTTPS only.
        -   `SameSite=Lax`: CSRF protection.
        -   `Max-Age`: 5 days (configurable).
5.  **Response**: The backend responds with success, and the browser stores the cookie.

### 1.2. Protected Endpoints

All API endpoints (except health checks and login) are protected. They require the `session` cookie to be present and valid.

-   If the cookie is missing or invalid: `401 Unauthorized`.
-   If the user is found but `is_approved` is false: `403 Forbidden`.

## 2. User Administration

By default, new users are **not approved** to use LLM features. An admin must manually approve them in the database.

### How to Approve a User

1.  Connect to the PostgreSQL database.
2.  Find the user by email or UID.
    ```sql
    SELECT * FROM users WHERE email = 'user@example.com';
    ```
3.  Update the `is_approved` flag to `true`.
    ```sql
    UPDATE users SET is_approved = true WHERE email = 'user@example.com';
    ```

## 3. LLM Audit Logging

Every interaction with an LLM endpoint (e.g., generating lessons, jobs, writing checks) is logged for audit purposes.

### Data Schema

The `llm_audit_logs` table stores the following information:

-   `id`: Primary Key.
-   `user_id`: Foreign Key to `users.id`.
-   `prompt_summary`: A summary or the topic of the prompt (e.g., "Photosynthesis").
-   `model_name`: The model(s) used (e.g., "gemini-1.5-pro").
-   `tokens_used`: Number of tokens consumed (if available).
-   `timestamp`: When the request was made.
-   `status`: Status of the request (e.g., "queued", "completed").

### Example Log Output

```json
{
  "id": 1,
  "user_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
  "prompt_summary": "Introduction to Quantum Physics",
  "model_name": "job:gpt-4,gemini-pro,gpt-3.5",
  "tokens_used": 150,
  "timestamp": "2023-10-27T10:00:00Z",
  "status": "job_queued"
}
```

## 4. Environment Configuration

Ensure the following environment variables are set:

-   `FIREBASE_PROJECT_ID`: Your Firebase Project ID.
-   `FIREBASE_SERVICE_ACCOUNT_JSON_PATH`: Path to the service account JSON file.
-   `DGS_PG_DSN`: PostgreSQL connection string.
-   `DGS_LLM_AUDIT_ENABLED`: Set to `true` to enable logging.
