# Authentication & LLM Audit Logging Flow

This document describes the authentication flow using Amazon Cognito and Google SSO, as well as the LLM audit logging mechanism.

## Authentication Flow

The DGS service uses Amazon Cognito for identity management, integrated with Google as a federated identity provider. The Backend-for-Frontend (BFF) pattern is used to secure the communication between the frontend and the DGS backend.

### 1. Google Login & Callback

1.  **Frontend**: Redirects the user to the Cognito Hosted UI (or constructs the authorization URL) with `identity_provider=Google`.
2.  **Cognito**: Handles the OAuth2 flow with Google.
3.  **Callback**: Upon successful authentication, Cognito redirects the user back to the DGS backend's callback endpoint: `/api/auth/callback` with an authorization `code`.

### 2. Code Exchange & Session Creation

1.  **Backend (`/api/auth/callback`)**:
    *   Receives the authorization `code`.
    *   Exchanges the `code` for tokens (`access_token`, `id_token`, `refresh_token`) using the Cognito Token Endpoint.
    *   Fetches user information from Cognito.
    *   **Admin Approval Check**: Verifies if the user's Cognito status is `CONFIRMED`. If not, returns `403 Forbidden`.
    *   **User Synchronization**: Checks if the user exists in the local `users` table (matched by `cognito_sub`). Creates or updates the user record.
    *   **Session Cookie**: Sets a secure, HttpOnly, SameSite=Lax cookie named `dgs_session` containing the access token (or a session identifier).

### 3. Protected Endpoints

*   **Middleware/Dependency**: Protected endpoints (like `/api/me` and `/v1/lessons/generate`) use a dependency `get_current_user` that:
    *   Reads the `dgs_session` cookie.
    *   Validates the token.
    *   Retrieves the user from the `users` table.
    *   Ensures the user is authorized.

### Testing Authentication

To test the `/api/me` endpoint using `curl`, you need a valid session cookie.

```bash
curl -v http://localhost:8080/api/me \
  -H "Cookie: dgs_session=<VALID_ACCESS_TOKEN>"
```

## LLM Audit Logging

Every call to an LLM API is logged to the `llm_audit_logs` table for auditing and tracking purposes.

### Mechanism

*   **Models**:
    *   `users`: Stores user information linked to Cognito.
    *   `llm_audit_logs`: Stores details of each LLM call.
*   **Logging**:
    *   An async utility `log_llm_call` is provided in `app/utils/audit_logging.py`.
    *   This function should be called whenever an LLM generation occurs, capturing:
        *   `user_id`: The ID of the authenticated user making the request.
        *   `prompt_summary`: A summary or full text of the prompt.
        *   `model_name`: The name of the model used (e.g., `gpt-4o`).
        *   `tokens_used`: Token usage count.
        *   `timestamp`: When the call occurred.
        *   `status`: Success or failure status.

### Testing LLM Logging

To test the logging, trigger a lesson generation (which calls the LLM) while authenticated.

```bash
curl -X POST http://localhost:8080/v1/lessons/generate \
  -H "Content-Type: application/json" \
  -H "Cookie: dgs_session=<VALID_ACCESS_TOKEN>" \
  -H "X-DGS-Dev-Key: <DEV_KEY>" \
  -d '{
    "topic": "Python Lists",
    "mode": "fast"
  }'
```

After the request, check the database:

```sql
SELECT * FROM llm_audit_logs;
```

## Configuration

Ensure the following environment variables are set in `.env`:

*   `COGNITO_USER_POOL_ID`
*   `COGNITO_APP_CLIENT_ID`
*   `COGNITO_CLIENT_SECRET`
*   `COGNITO_DOMAIN`
*   `DATABASE_URL` (or `DGS_PG_DSN`)
*   `DGS_LLM_AUDIT_ENABLED=true`
