# Infrastructure Setup for Cloud Tasks Worker

To enable secure Cloud Run-to-Cloud Run invocation for the new lesson generation worker, you must grant the `roles/run.invoker` role to the service account used by Cloud Tasks.

## CLI Command

Replace `<SERVICE_NAME>` with your Cloud Run service name (e.g., `dylen-api`) and `<INVOKER_SERVICE_ACCOUNT_EMAIL>` with the email of the service account attached to your Cloud Tasks queue (or the one you configured as `DYLEN_CLOUD_RUN_INVOKER_SERVICE_ACCOUNT`).

```bash
gcloud run services add-iam-policy-binding <SERVICE_NAME> \
  --member=serviceAccount:<INVOKER_SERVICE_ACCOUNT_EMAIL> \
  --role=roles/run.invoker \
  --region=<REGION>
```

## Terraform

```hcl
resource "google_cloud_run_service_iam_member" "invoker" {
  service  = google_cloud_run_service.api.name
  location = google_cloud_run_service.api.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.cloud_tasks_service_account_email}"
}
```

## Environment Variables

Ensure `DYLEN_CLOUD_RUN_INVOKER_SERVICE_ACCOUNT` is set in your environment if you want the application to explicitly attach OIDC tokens using this email.

## Service Timeout

Ensure your Cloud Run service has a sufficient timeout (e.g., 300 seconds) to handle lesson generation.

```bash
gcloud run services update <SERVICE_NAME> --timeout=300
```
