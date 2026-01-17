# GitHub Secrets Quick Reference

This document lists all the GitHub secrets you need to configure for the DGS CI/CD pipeline.

## Security Scanning Secrets

### Snyk (Required)

**`SNYK_TOKEN`**
- **Purpose:** Authenticate with Snyk for SCA and container scanning
- **How to get:**
  1. Go to https://app.snyk.io/account
  2. Click on "Account Settings"
  3. Navigate to "API Token"
  4. Click "Click to show" and copy the token
- **Used by:** `security-sca`, `security-container` jobs

### Semgrep (Optional)

**`SEMGREP_APP_TOKEN`**
- **Purpose:** Enable Semgrep Cloud integration and PR comments
- **How to get:**
  1. Go to https://semgrep.dev/manage/settings/tokens
  2. Create a new token
  3. Copy the token value
- **Used by:** `security-sast-semgrep` job
- **Note:** Optional - scans will still work without it, but won't have PR comments

---

## GCP Deployment Secrets

### Required GCP Secrets

**`GCP_PROJECT_ID`**
- **Purpose:** Your GCP project ID
- **How to get:** Run `gcloud config get-value project` or check GCP Console
- **Example:** `dgs-production`

**`GCP_WORKLOAD_IDENTITY_PROVIDER`**
- **Purpose:** Workload Identity Provider resource name for secure GitHub Actions auth
- **How to get:** From Step 9 in `docs/gcp-setup-guide.md`
- **Format:** `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_NAME/providers/PROVIDER_NAME`
- **Example:** `projects/123456789/locations/global/workloadIdentityPools/github-actions-pool/providers/github-provider`

**`GCP_SERVICE_ACCOUNT`**
- **Purpose:** Service account email for GitHub Actions deployment
- **How to get:** From Step 7 in `docs/gcp-setup-guide.md`
- **Format:** `SERVICE_ACCOUNT_NAME@PROJECT_ID.iam.gserviceaccount.com`
- **Example:** `github-actions-deploy@dgs-production.iam.gserviceaccount.com`

**`GCP_REGION`**
- **Purpose:** GCP region for Cloud Run and Artifact Registry
- **How to get:** Choose your preferred region
- **Example:** `us-central1`
- **Options:** `us-central1`, `us-east1`, `europe-west1`, `asia-northeast1`, etc.

**`GCP_CLOUD_SQL_INSTANCE`**
- **Purpose:** Cloud SQL connection name
- **How to get:** From Step 3 in `docs/gcp-setup-guide.md`
- **Format:** `PROJECT_ID:REGION:INSTANCE_NAME`
- **Example:** `dgs-production:us-central1:dgs-postgres`

**`GCP_ARTIFACT_REGISTRY`**
- **Purpose:** Full path to Artifact Registry repository
- **How to get:** From Step 5 in `docs/gcp-setup-guide.md`
- **Format:** `REGION-docker.pkg.dev/PROJECT_ID/REPOSITORY_NAME`
- **Example:** `us-central1-docker.pkg.dev/dgs-production/dgs-docker`

**`GCP_CLOUD_RUN_SERVICE_ACCOUNT`**
- **Purpose:** Service account email for Cloud Run service
- **How to get:** From Step 6 in `docs/gcp-setup-guide.md`
- **Format:** `SERVICE_ACCOUNT_NAME@PROJECT_ID.iam.gserviceaccount.com`
- **Example:** `dgs-cloud-run@dgs-production.iam.gserviceaccount.com`

---

## How to Add Secrets to GitHub

1. Go to your GitHub repository
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Enter the secret name (exactly as shown above)
5. Paste the secret value
6. Click **Add secret**

---

## Security Best Practices

✅ **DO:**
- Use Workload Identity Federation (no service account keys!)
- Store all sensitive data in GCP Secret Manager
- Rotate secrets regularly
- Use least-privilege IAM roles
- Enable audit logging

❌ **DON'T:**
- Store service account JSON keys in GitHub secrets
- Commit secrets to version control
- Share secrets via insecure channels
- Use overly permissive IAM roles

---

## Verification

After adding all secrets, verify they're configured correctly:

```bash
# Check GitHub secrets (you won't see values, just names)
gh secret list

# Expected output:
# SNYK_TOKEN
# SEMGREP_APP_TOKEN (optional)
# GCP_PROJECT_ID
# GCP_WORKLOAD_IDENTITY_PROVIDER
# GCP_SERVICE_ACCOUNT
# GCP_REGION
# GCP_CLOUD_SQL_INSTANCE
# GCP_ARTIFACT_REGISTRY
# GCP_CLOUD_RUN_SERVICE_ACCOUNT
```

---

## Troubleshooting

### Secret not found error

**Error:** `Context access might be invalid: SECRET_NAME`

**Solution:** Verify the secret name matches exactly (case-sensitive) and is added to the repository (not organization or environment secrets).

### Workload Identity authentication fails

**Error:** `Failed to authenticate to Google Cloud`

**Solution:** 
1. Verify `GCP_WORKLOAD_IDENTITY_PROVIDER` format is correct
2. Check service account has `roles/iam.workloadIdentityUser` binding
3. Verify attribute condition in Workload Identity Provider matches your GitHub org

### Cloud SQL connection fails

**Error:** `Could not connect to Cloud SQL instance`

**Solution:**
1. Verify `GCP_CLOUD_SQL_INSTANCE` format is `PROJECT:REGION:INSTANCE`
2. Check Cloud Run service account has `roles/cloudsql.client` role
3. Ensure Cloud SQL instance is running

---

## Quick Setup Script

Save this as `setup-github-secrets.sh` and run it after completing the GCP setup:

```bash
#!/bin/bash

# Load variables from GCP setup
source gcp-setup-vars.sh

# Add secrets to GitHub (requires gh CLI)
gh secret set SNYK_TOKEN --body "$SNYK_TOKEN"
gh secret set GCP_PROJECT_ID --body "$PROJECT_ID"
gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --body "$PROVIDER_NAME"
gh secret set GCP_SERVICE_ACCOUNT --body "$DEPLOY_SA_EMAIL"
gh secret set GCP_REGION --body "$REGION"
gh secret set GCP_CLOUD_SQL_INSTANCE --body "$SQL_CONNECTION_NAME"
gh secret set GCP_ARTIFACT_REGISTRY --body "${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}"
gh secret set GCP_CLOUD_RUN_SERVICE_ACCOUNT --body "$SA_EMAIL"

echo "✅ All secrets configured!"
```

---

## Summary

Total secrets needed: **8-9**
- **2** for security scanning (1 required, 1 optional)
- **7** for GCP deployment (all required)

Once configured, your CI/CD pipeline will:
1. Run security scans on every commit
2. Deploy to GCP Cloud Run on main branch pushes
3. Use secure, keyless authentication
4. Connect to Cloud SQL PostgreSQL
5. Inject secrets from Secret Manager
