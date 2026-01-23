# Notifications Spec (Email + Push)

## Goals

- Notify users when key events complete without blocking core product flows.
- Keep notification delivery secure-by-default and avoid persisting unnecessary user PII.
- Provide a modular design that supports multiple channels (email and push) with clear extension points.

## Non-Goals (for this iteration)

- Guaranteed exactly-once delivery (outbox + dedupe keys is a follow-up).
- Rich templating, HTML emails, attachments, or including lesson content in notifications.
- Full push provider integration (FCM/APNs), device token lifecycle, or user preference management UI.

## Events

### `lesson.generated`

Triggered when a lesson is fully generated and durably persisted.

- Synchronous endpoint: `POST /v1/lessons/generate`
- Async jobs: `POST /v1/jobs` and `POST /v1/lessons/jobs` (after job completion + lesson persistence)

Payload (conceptual):
- `lesson_id`: string
- `topic`: string
- Recipient resolved from authenticated user (sync) or job `_meta.user_id` (async)

### `user.account_approved`

Triggered when an admin approves a user account via the admin endpoint.

- Endpoint: `PATCH /admin/users/{user_id}/approve` (admin-only)

Payload (conceptual):
- `user_id`: UUID
- `email`: string

## Channels

### Email

Implementation:
- Server-side MailerSend API sender (`app.notifications.email_sender.MailerSendEmailSender`).
- Disabled by default; enabled only via explicit environment flags.

Security:
- HTML + plain-text multipart content with template placeholders, and minimal content (no lesson body).
- Transport uses HTTPS to MailerSend.
- No provider keys are shipped to clients; all sending happens server-side.
 - Placeholders are HTML-escaped before rendering.

### Push Notifications

Implementation:
- Interface exists (`app.notifications.contracts.PushSender`), default is a no-op sender.
- Future integration: Firebase Cloud Messaging (FCM) or APNs with device token storage and opt-in preferences.

## Data Handling and Privacy

- Jobs persist only `_meta.user_id` (not email) inside `dgs_jobs.request` to enable worker-side recipient resolution.
- Email addresses are sourced from the `users` table at send time.
- Notification content avoids including sensitive artifacts or generated lesson content.
- Failures are logged server-side; avoid logging full user emails when possible.
- Outbound email sends are logged in Postgres (`email_delivery_logs`) with `template_id`, `placeholders` (JSON), and provider identifiers.

## Reliability and Failure Modes

Current behavior (best-effort):
- Notification delivery never fails the user’s request/job completion.
- Notifications are sent only after the state change is committed (lesson persisted / approval committed).
- Delivery exceptions are caught and logged.
- Delivery attempts are recorded in `email_delivery_logs` even when provider calls fail.

Known limitations:
- Duplicate sends are possible if the same completion pathway is re-run (e.g., retries without dedupe/outbox).

Follow-up recommendations:
- Add an outbox table and background dispatcher with dedupe keys for exactly-once semantics.
- Add per-user preferences (email/push opt-in) and per-event routing.

## Configuration

Email notifications are disabled unless explicitly enabled.

Required when enabled:
- `DGS_EMAIL_NOTIFICATIONS_ENABLED=true`
- `DGS_EMAIL_FROM_ADDRESS`
- `DGS_EMAIL_PROVIDER=mailersend`
- `DGS_MAILERSEND_API_KEY`

Optional:
- `DGS_EMAIL_FROM_NAME`
- `DGS_MAILERSEND_TIMEOUT_SECONDS` (default `10`)
- `DGS_MAILERSEND_BASE_URL` (default `https://api.mailersend.com/v1`)

## Extension Points

- Implement a real push sender in `app.notifications.push_sender`.
- Add more email templates under `dgs-backend/app/notifications/templates/`.
- Add durable outbox + retry logic behind `NotificationService.send_email_template/send_push`.
