# GCP Cloud Run Deployment Setup Guide

Complete step-by-step guide for deploying the DGS application to Google Cloud Platform using Cloud Run and Cloud SQL.

## Prerequisites

- Google Cloud Platform account
- `gcloud` CLI installed ([Install Guide](https://cloud.google.com/sdk/docs/install))
- GitHub repository with admin access
- Docker installed locally (for testing)

---

## Part 1: GCP Project Setup

### Step 1: Create or Select a GCP Project

```bash
# Login to GCP
gcloud auth login

# Create a new project (or use existing)
export PROJECT_ID="dgs-production"  # Change this to your project ID
gcloud projects create $PROJECT_ID --name="DGS Production"

# Set as default project
gcloud config set project $PROJECT_ID

# Enable billing (required - do this in GCP Console)
# Go to: https://console.cloud.google.com/billing
```

### Step 2: Enable Required APIs

```bash
# Enable all required APIs
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  compute.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com
```

**Wait 2-3 minutes** for APIs to be fully enabled.

---

## Part 2: Cloud SQL PostgreSQL Setup

### Step 3: Create Cloud SQL Instance

```bash
# Set variables
export REGION="us-central1"  # Change to your preferred region
export SQL_INSTANCE_NAME="dgs-postgres"
export DB_NAME="dgs"
export DB_USER="dgs_user"

# Create PostgreSQL instance (this takes 5-10 minutes)
gcloud sql instances create $SQL_INSTANCE_NAME \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=$REGION \
  --network=default \
  --no-assign-ip \
  --database-flags=cloudsql.iam_authentication=on

# Create database
gcloud sql databases create $DB_NAME \
  --instance=$SQL_INSTANCE_NAME

# Create database user
gcloud sql users create $DB_USER \
  --instance=$SQL_INSTANCE_NAME \
  --password=$(openssl rand -base64 32)

# Get the connection name (save this!)
export SQL_CONNECTION_NAME=$(gcloud sql instances describe $SQL_INSTANCE_NAME \
  --format='value(connectionName)')
echo "Cloud SQL Connection Name: $SQL_CONNECTION_NAME"
```

**Save the connection name** - you'll need it later!

### Step 4: Store Database Password in Secret Manager

```bash
# Generate a secure password
export DB_PASSWORD=$(openssl rand -base64 32)

# Store in Secret Manager
echo -n "$DB_PASSWORD" | gcloud secrets create dgs-db-password \
  --data-file=- \
  --replication-policy="automatic"

# Update the SQL user password
gcloud sql users set-password $DB_USER \
  --instance=$SQL_INSTANCE_NAME \
  --password=$DB_PASSWORD

echo "Database password stored in Secret Manager as 'dgs-db-password'"
```

---

## Part 3: Artifact Registry Setup

### Step 5: Create Docker Repository

```bash
# Create Artifact Registry repository
export ARTIFACT_REPO="dgs-docker"

gcloud artifacts repositories create $ARTIFACT_REPO \
  --repository-format=docker \
  --location=$REGION \
  --description="Docker images for DGS application"

# Configure Docker authentication
gcloud auth configure-docker ${REGION}-docker.pkg.dev

echo "Artifact Registry: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}"
```

---

## Part 4: Service Account Setup

### Step 6: Create Service Account for Cloud Run

```bash
# Create service account
export SA_NAME="dgs-cloud-run"
export SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create $SA_NAME \
  --display-name="DGS Cloud Run Service Account"

# Grant necessary permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudsql.client"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor"

echo "Service Account: $SA_EMAIL"
```

### Step 7: Create Service Account for GitHub Actions

```bash
# Create deployment service account
export DEPLOY_SA_NAME="github-actions-deploy"
export DEPLOY_SA_EMAIL="${DEPLOY_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create $DEPLOY_SA_NAME \
  --display-name="GitHub Actions Deployment Service Account"

# Grant deployment permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${DEPLOY_SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser"

echo "Deployment Service Account: $DEPLOY_SA_EMAIL"
```

---

## Part 5: Workload Identity Federation (Secure GitHub Actions Auth)

This is the **secure way** to authenticate GitHub Actions without service account keys!

### Step 8: Create Workload Identity Pool

```bash
# Create workload identity pool
export POOL_NAME="github-actions-pool"

gcloud iam workload-identity-pools create $POOL_NAME \
  --location="global" \
  --display-name="GitHub Actions Pool"

# Get the pool ID
export POOL_ID=$(gcloud iam workload-identity-pools describe $POOL_NAME \
  --location="global" \
  --format="value(name)")

echo "Workload Identity Pool: $POOL_ID"
```

### Step 9: Create Workload Identity Provider

```bash
# Replace with your GitHub org/username and repo
export GITHUB_ORG="your-github-org"  # CHANGE THIS
export GITHUB_REPO="dgs"              # CHANGE THIS

# Create provider
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --location="global" \
  --workload-identity-pool=$POOL_NAME \
  --display-name="GitHub Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository_owner == '${GITHUB_ORG}'" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# Get the provider resource name
export PROVIDER_NAME=$(gcloud iam workload-identity-pools providers describe "github-provider" \
  --location="global" \
  --workload-identity-pool=$POOL_NAME \
  --format="value(name)")

echo "Workload Identity Provider: $PROVIDER_NAME"
```

### Step 10: Bind Service Account to Workload Identity

```bash
# Allow GitHub Actions from your repo to impersonate the service account
gcloud iam service-accounts add-iam-policy-binding $DEPLOY_SA_EMAIL \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_ID}/attribute.repository/${GITHUB_ORG}/${GITHUB_REPO}"

echo "✅ Workload Identity Federation configured!"
```

---

## Part 6: GitHub Secrets Configuration

### Step 11: Add Secrets to GitHub Repository

Go to your GitHub repository: `https://github.com/${GITHUB_ORG}/${GITHUB_REPO}/settings/secrets/actions`

Click **"New repository secret"** and add each of the following:

#### Required Secrets:

1. **`GCP_PROJECT_ID`**
   ```bash
   # Copy this value:
   echo $PROJECT_ID
   ```

2. **`GCP_WORKLOAD_IDENTITY_PROVIDER`**
   ```bash
   # Copy this value:
   echo $PROVIDER_NAME
   ```

3. **`GCP_SERVICE_ACCOUNT`**
   ```bash
   # Copy this value:
   echo $DEPLOY_SA_EMAIL
   ```

4. **`GCP_REGION`**
   ```bash
   # Copy this value:
   echo $REGION
   ```

5. **`GCP_CLOUD_SQL_INSTANCE`**
   ```bash
   # Copy this value:
   echo $SQL_CONNECTION_NAME
   ```

6. **`GCP_ARTIFACT_REGISTRY`**
   ```bash
   # Copy this value:
   echo "${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}"
   ```

7. **`GCP_CLOUD_RUN_SERVICE_ACCOUNT`**
   ```bash
   # Copy this value:
   echo $SA_EMAIL
   ```

#### Security Secrets (Already in Secret Manager):

These are stored in GCP Secret Manager and accessed by Cloud Run:
- `dgs-db-password` - Database password
- Add other secrets as needed (API keys, etc.)

---

## Part 7: Store Application Secrets in Secret Manager

### Step 12: Create Application Secrets

```bash
# DGS Dev Key (for API authentication)
echo -n "your-secure-dev-key-here" | gcloud secrets create dgs-dev-key \
  --data-file=- \
  --replication-policy="automatic"

# OpenRouter API Key
echo -n "your-openrouter-api-key" | gcloud secrets create openrouter-api-key \
  --data-file=- \
  --replication-policy="automatic"

# Gemini API Key
echo -n "your-gemini-api-key" | gcloud secrets create gemini-api-key \
  --data-file=- \
  --replication-policy="automatic"

# Grant Cloud Run service account access to secrets
for secret in dgs-db-password dgs-dev-key openrouter-api-key gemini-api-key; do
  gcloud secrets add-iam-policy-binding $secret \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor"
done

echo "✅ Application secrets created and permissions granted!"
```

---

## Part 8: Test Deployment (Manual)

### Step 13: Build and Push Docker Image

```bash
# From your project root
cd /path/to/dgs

# Build image
export IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/dgs-backend:latest"

docker build -t $IMAGE_NAME .

# Push to Artifact Registry
docker push $IMAGE_NAME

echo "✅ Image pushed: $IMAGE_NAME"
```

### Step 14: Deploy to Cloud Run

```bash
# Deploy to Cloud Run
gcloud run deploy dgs-backend \
  --image=$IMAGE_NAME \
  --platform=managed \
  --region=$REGION \
  --service-account=$SA_EMAIL \
  --add-cloudsql-instances=$SQL_CONNECTION_NAME \
  --set-env-vars="DGS_PG_DSN=/cloudsql/${SQL_CONNECTION_NAME}" \
  --set-secrets="DGS_DEV_KEY=dgs-dev-key:latest,OPENROUTER_API_KEY=openrouter-api-key:latest,GEMINI_API_KEY=gemini-api-key:latest" \
  --allow-unauthenticated \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10

# Get the service URL
export SERVICE_URL=$(gcloud run services describe dgs-backend \
  --region=$REGION \
  --format='value(status.url)')

echo "✅ Service deployed at: $SERVICE_URL"
```

### Step 15: Test the Deployment

```bash
# Test health endpoint
curl $SERVICE_URL/health

# Test API
curl -H "X-DGS-Dev-Key: your-dev-key" $SERVICE_URL/api/endpoint
```

---

## Part 9: GitHub Actions Workflow

The GitHub Actions workflow will now automatically:
1. Authenticate using Workload Identity Federation (no keys!)
2. Build Docker image
3. Push to Artifact Registry
4. Deploy to Cloud Run
5. Run on every push to `main` branch

**No additional configuration needed** - just push to main!

---

## Security Best Practices

### ✅ What We Did Right:

1. **Workload Identity Federation** - No service account keys stored in GitHub
2. **Secret Manager** - All sensitive data in GCP Secret Manager
3. **Least Privilege** - Service accounts have minimal required permissions
4. **Private SQL** - Cloud SQL has no public IP
5. **IAM Authentication** - Cloud SQL supports IAM authentication

### 🔒 Additional Security Recommendations:

1. **Enable VPC Connector** (for production):
   ```bash
   gcloud compute networks vpc-access connectors create dgs-connector \
     --region=$REGION \
     --range=10.8.0.0/28
   ```

2. **Restrict Cloud Run Access** (if needed):
   ```bash
   # Remove --allow-unauthenticated and add IAM bindings
   gcloud run services add-iam-policy-binding dgs-backend \
     --region=$REGION \
     --member="user:your-email@example.com" \
     --role="roles/run.invoker"
   ```

3. **Enable Cloud Armor** (DDoS protection)
4. **Set up Cloud Monitoring** and alerts
5. **Enable Audit Logs**

---

## Troubleshooting

### Issue: "Permission denied" errors

**Solution:** Verify service account permissions:
```bash
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${DEPLOY_SA_EMAIL}"
```

### Issue: Cloud SQL connection fails

**Solution:** Check Cloud SQL instance is running:
```bash
gcloud sql instances describe $SQL_INSTANCE_NAME
```

Verify Cloud Run has `cloudsql.client` role:
```bash
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${SA_EMAIL}"
```

### Issue: GitHub Actions authentication fails

**Solution:** Verify Workload Identity Federation:
```bash
gcloud iam service-accounts get-iam-policy $DEPLOY_SA_EMAIL
```

Check the attribute condition matches your GitHub org.

---

## Summary Checklist

- [ ] GCP project created and billing enabled
- [ ] All APIs enabled
- [ ] Cloud SQL PostgreSQL instance created
- [ ] Database and user created
- [ ] Artifact Registry repository created
- [ ] Service accounts created (Cloud Run + GitHub Actions)
- [ ] Workload Identity Federation configured
- [ ] GitHub secrets added (7 secrets)
- [ ] Application secrets in Secret Manager
- [ ] Manual deployment tested successfully
- [ ] GitHub Actions workflow ready to use

---

## Quick Reference

### Important Resource Names

Save these for future reference:

```bash
# Project
PROJECT_ID: $PROJECT_ID

# Cloud SQL
SQL_CONNECTION_NAME: $SQL_CONNECTION_NAME
DATABASE: $DB_NAME
DB_USER: $DB_USER

# Artifact Registry
REGISTRY: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}

# Service Accounts
CLOUD_RUN_SA: $SA_EMAIL
DEPLOY_SA: $DEPLOY_SA_EMAIL

# Workload Identity
PROVIDER: $PROVIDER_NAME

# Cloud Run
SERVICE_URL: $SERVICE_URL
```

### Useful Commands

```bash
# View Cloud Run logs
gcloud run services logs read dgs-backend --region=$REGION --limit=50

# View Cloud SQL logs
gcloud sql operations list --instance=$SQL_INSTANCE_NAME

# Update Cloud Run service
gcloud run services update dgs-backend --region=$REGION [options]

# List secrets
gcloud secrets list

# Access secret value (for debugging)
gcloud secrets versions access latest --secret=dgs-dev-key
```

---

## Next Steps

1. **Push to main branch** - GitHub Actions will automatically deploy
2. **Set up monitoring** - Configure Cloud Monitoring alerts
3. **Configure custom domain** - Map your domain to Cloud Run
4. **Set up CI/CD for staging** - Create staging environment
5. **Enable Cloud CDN** - For static assets (if needed)

🎉 **You're all set!** Your application will now automatically deploy to GCP Cloud Run on every push to main.
