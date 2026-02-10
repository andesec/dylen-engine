# Spec: Web Push Backend Implementation (FastAPI + Postgres)

## 1. Objective
Implement a robust backend service to manage Web Push subscriptions and trigger notifications. This must integrate with the existing notifications table while maintaining high security standards.

## 2. Database Design (Postgres)
Create a table `web_push_subscriptions` linked to your existing User table.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | UUID | Primary Key |
| `user_id` | UUID | Foreign Key (on_delete=CASCADE) |
| `endpoint` | Text | The unique push service URL (Unique Constraint) |
| `p256dh` | Text | Client public key (Base64) |
| `auth` | Text | Client auth secret (Base64) |
| `user_agent` | Text | To identify which device is registered |
| `created_at` | Timestamp | Creation timestamp |

## 3. API Endpoints (FastAPI)

### A. POST /api/v1/push/subscribe
*   **Body:** The standard JSON subscription object from the browser.
*   **Logic:** Upsert the record based on the `endpoint`. Ensure the `user_id` is derived from the authenticated session (JWT/Session).
*   **Security:** Sanitize inputs and validate that the `endpoint` URL belongs to a known push service (Google, Mozilla, Apple).

### B. DELETE /api/v1/push/unsubscribe
*   **Logic:** Delete the subscription record for the current user matching the provided endpoint.

## 4. Notification Dispatch Service
Use the `pywebpush` library.

### A. The Sender Function
*   **Input:** `user_id`, `notification_id` (from your existing table).
*   **Process:**
    1.  Fetch the notification details (title, body, slug) from your existing notifications table.
    2.  Fetch all `web_push_subscriptions` for that `user_id`.
    3.  Loop through and send the payload:
        ```json
        {
          "title": "New Update!",
          "body": "...",
          "data": { "url": "/notifications/[ID]" }
        }
        ```
*   **Critical Error Handling:**
    *   If `pywebpush` returns a **410 Gone** or **404 Not Found**, the token is invalid/expired. **Delete it from the DB immediately.**
    *   Implement a retry mechanism with exponential backoff for 5xx errors.

### B. Trigger Integration
*   Use a Post-Save Hook or a FastAPI `BackgroundTask` whenever a new record is added to your existing notifications table.
*   **Performance:** Never block the main API response for push delivery; always use async background tasks.

## 5. Environment & Security
*   **VAPID Keys:** Generate using `openssl` or `pywebpush`.
*   **Claims:** The `sub` claim must be a `mailto:` or a website URL (required by push services).
*   **Rate Limiting:** Implement rate limiting on the `/subscribe` endpoint to prevent bot spam.
