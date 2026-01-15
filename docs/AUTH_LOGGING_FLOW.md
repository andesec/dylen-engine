# Authentication & Logging Flow

## Authentication Flow

1.  **Frontend Login:**
    - The frontend authenticates the user using Firebase Authentication (Google provider, etc.).
    - On successful login, the frontend receives a Firebase ID Token.
    - The frontend sends this ID Token to the DGS backend via `POST /api/auth/login`.

2.  **Backend Verification & Cookie Issuance:**
    - The `POST /api/auth/login` endpoint verifies the ID Token using the Firebase Admin SDK.
    - If valid, DGS creates a secure, HttpOnly, SameSite=Lax session cookie using `firebase_admin.auth.create_session_cookie`.
    - This cookie is sent back to the client and will be used for subsequent requests.
    - A corresponding user record is created or updated in the `users` PostgreSQL table.

3.  **Access Control:**
    - For all protected endpoints, the `get_current_active_user` dependency is used.
    - This dependency:
        - Retrieves the session cookie.
        - Verifies it using `firebase_admin.auth.verify_session_cookie`.
        - Fetches the user from the `users` table.
        - Checks if `user.is_approved` is `True`.
    - If any check fails, a `401 Unauthorized` or `403 Forbidden` response is returned.

## Manual User Approval

By default, new users have `is_approved = False` and cannot access LLM features. To approve a user:

1.  Connect to the PostgreSQL database.
2.  Find the user by email or ID:
    ```sql
    SELECT * FROM users WHERE email = 'user@example.com';
    ```
3.  Update the `is_approved` flag:
    ```sql
    UPDATE users SET is_approved = true WHERE id = <user_id>;
    ```

## LLM Audit Logging

Every interaction with an LLM provider is logged in the `llm_audit_logs` table.

### Log Output Example (Database Record)

| Field | Value |
| :--- | :--- |
| `id` | `1024` |
| `user_id` | `42` |
| `prompt_summary` | `Generate a lesson about Python loops...` |
| `model_name` | `openai/gpt-oss-20b:free` |
| `tokens_used` | `1500` |
| `timestamp` | `2023-10-27 10:30:00` |
| `status` | `success` |

The `prompt_summary` is a truncated version of the actual prompt to save space while retaining context.
