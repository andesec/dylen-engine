# Cloud Tasks & Job Processing

This service uses Google Cloud Tasks to manage background job execution (e.g., lesson generation). This ensures reliability, retries, and rate limiting separate from the web server instance.

## Architecture

1.  **Job Creation**: When a user POSTs to `/v1/jobs`, a `JobRecord` is created in Postgres with status `queued`.
2.  **Task Enqueue**: The service dispatches a task to the configured queue.
    *   **Production**: Uses `google.cloud.tasks_v2` to push a task to a Cloud Tasks Queue.
    *   **Local Development**: Uses `httpx` to POST directly to the local `/internal/tasks/process-job` endpoint, simulating the Cloud Tasks push.
3.  **Task Execution**: The job queue (or local dispatcher) POSTs to `/internal/tasks/process-job`.
4.  **Processing**: The handler at `/internal/tasks/process-job` runs the `JobProcessor` synchronously.

## Configuration

Ensure the following environment variables are set in `app/config.py` or `.env`:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DYLEN_JOBS_AUTO_PROCESS` | Enable automatic job processing? | `True` |
| `DYLEN_TASK_SERVICE_PROVIDER` | `gcp` or `local-http` | `local-http` |
| `DYLEN_BASE_URL` | The public URL of this service (used by Cloud Tasks) | `http://localhost:8000` |
| `DYLEN_CLOUD_TASKS_QUEUE_PATH` | Full GCP Queue Path (projects/PROJ/locations/LOC/queues/Q) | `None` |

## Local Development

For local development, the system defaults to `local-http`.

1.  Start the service: `uvicorn app.main:app --reload`
2.  Create a job via Swagger UI or curl.
3.  Observe logs:
    ```
    INFO:     Dispatching task locally to http://localhost:8000/internal/tasks/process-job
    INFO:     Received task for job <JOB_ID>
    ...
    INFO:     Job completed successfully.
    ```
4.  Note: when `DYLEN_BASE_URL` points at `localhost`/`127.0.0.1`, local dispatch routes requests in-process (ASGI transport) and ignores proxy env vars for reliability.

## Cloud Deployment (GCP)

To enable Cloud Tasks:

1.  **Create a Queue**:
    ```bash
    gcloud tasks queues create dylen-jobs-queue --location=us-central1
    ```
2.  **Configure Service**:
    Set env vars:
    ```
    DYLEN_TASK_SERVICE_PROVIDER=gcp
    DYLEN_CLOUD_TASKS_QUEUE_PATH=projects/YOUR_PROJECT/locations/us-central1/queues/dylen-jobs-queue
    DYLEN_BASE_URL=https://your-cloud-run-service-url.run.app
    ```
3.  **IAM Permissions**:
    *   The service account running the engine needs `roles/cloudtasks.enqueuer`.
    *   The **Cloud Tasks Queue** needs a service account with `roles/run.invoker` to call the Cloud Run service (configured via OIDC token on the task).

## Troubleshooting

*   **Job stuck in `queued`**: Check if `DYLEN_JOBS_AUTO_PROCESS` is `True`. Check logs for "Failed to enqueue task".
*   **Task fails repeatedly**: Cloud Tasks will retry automatically with exponential backoff. Check the handler logs for exceptions.
*   **`Server disconnected without sending a response`**: Ensure `DYLEN_BASE_URL` is set and points to `http://localhost:<port>` for local development, and avoid proxying internal requests (the local enqueuer ignores proxy env vars by default).

## Scheduled Maintenance (Cloud Scheduler)

This service supports scheduled maintenance via Cloud Scheduler calling an admin trigger endpoint that enqueues a maintenance job into Cloud Tasks.

### Archive old lessons (daily 1am UTC)

1. Create a Cloud Scheduler job to call:
   - `POST /admin/maintenance/archive-lessons`
2. Authenticate the call using either:
   - `DYLEN_TASK_SECRET` (recommended for dev/staging), or
   - Cloud Scheduler OIDC → Cloud Run IAM (recommended for production)
3. Schedule time:
   - **1am UTC** daily.

Why:
* This keeps end-user lesson history bounded per tier by archiving older lessons in Postgres and denying access to archived lessons in user endpoints.
