#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy_stage_now.sh \
    --project-id <gcp_project_id> \
    --region <gcp_region> \
    --ar-repo <artifact_registry_repo> \
    --image <image_name> \
    --service <cloud_run_service_name> \
    --migrate-job <cloud_run_job_name> \
    --run-sa <runtime_service_account_email> \
    --cloudsql-instance <project:region:instance> \
    [--db-name <cloudsql_database_name>] \
    [--db-user <cloudsql_database_user>] \
    [--db-password-secret <secret_name_with_db_password>] \
    [--cloud-tasks-queue <queue_name>] \
    [--cloud-tasks-invoker-sa <service_account_email>] \
    [--illustration-bucket <gcs_bucket_name>] \
    --env-file <path_to_env_file> \
    [--allowed-origins <csv_origins>] \
    [--base-url <public_base_url>] \
    [--internal-service-url <internal_callback_url>] \
    [--environment-tag-value-id <tagValues/123456789>] \
    [--org-id <organization_id>] \
    [--environment-tag-short-name <development|staging|test|production>] \
    [--skip-project-env-tag] \
    [--dylen-env <development|stage|production|test>] \
    [--tag <image_tag>] \
    [--allow-unknown-env] \
    [--skip-secrets-stage] \
    [--skip-dsn-secret-update] \
    [--skip-firebase-sa-setup] \
    [--skip-cloud-tasks-setup] \
    [--skip-storage-setup] \
    [--skip-env-sync] \
    [--skip-secret-sync] \
    [--skip-auth-login] \
    [--skip-health-check]

Example:
  scripts/deploy_stage_now.sh \
    --project-id dylen-stage-485900 \
    --region us-central1 \
    --ar-repo dylen-stage \
    --image app \
    --service dylen-engine-stage \
    --migrate-job dylen-engine-stage-migrate \
    --run-sa sa-dylen-stage@dylen-stage-485900.iam.gserviceaccount.com \
    --cloudsql-instance dylen-stage-485900:us-central1:dylen-stage \
    --db-name dylen-stage \
    --db-user dylen-stage-user \
    --db-password-secret STAGE_DB_PASSWORD \
    --cloud-tasks-queue dylen-jobs-queue \
    --cloud-tasks-invoker-sa sa-cloud-tasks-invoker@dylen-stage-485900.iam.gserviceaccount.com \
    --illustration-bucket dylen-stage-illustrations \
    --env-file .env-stage \
    --org-id 123456789012 \
    --environment-tag-short-name staging \
    --dylen-env stage \
    --allow-unknown-env \
    --skip-secrets-stage \
    --skip-env-sync \
    --allowed-origins https://stage.dylen.app

Minimal (reads DEPLOY_* values from .env-stage):
  scripts/deploy_stage_now.sh --env-file .env-stage --skip-project-env-tag --allow-unknown-env --skip-secrets-stage
EOF
}

PROJECT_ID=""
REGION=""
AR_REPO=""
IMAGE=""
SERVICE=""
MIGRATE_JOB=""
RUN_SA=""
CLOUDSQL_INSTANCE=""
DB_NAME=""
DB_USER=""
DB_PASSWORD_SECRET=""
CLOUD_TASKS_QUEUE_NAME=""
CLOUD_TASKS_INVOKER_SA=""
ILLUSTRATION_BUCKET=""
ENV_FILE=""
ALLOWED_ORIGINS=""
BASE_URL_OVERRIDE=""
INTERNAL_SERVICE_URL_OVERRIDE=""
DYLEN_ENV_VALUE=""
ENVIRONMENT_TAG_VALUE_ID=""
ORG_ID=""
ENVIRONMENT_TAG_SHORT_NAME="staging"
SKIP_PROJECT_ENV_TAG="0"
TAG=""
SKIP_SECRET_SYNC="0"
SKIP_ENV_SYNC="0"
SKIP_SECRETS_STAGE="0"
SKIP_DSN_SECRET_UPDATE="0"
SKIP_FIREBASE_SA_SETUP="0"
SKIP_CLOUD_TASKS_SETUP="0"
SKIP_STORAGE_SETUP="0"
SKIP_AUTH_LOGIN="0"
SKIP_HEALTH_CHECK="0"
ALLOW_UNKNOWN_ENV="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      PROJECT_ID="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    --ar-repo)
      AR_REPO="$2"
      shift 2
      ;;
    --image)
      IMAGE="$2"
      shift 2
      ;;
    --service)
      SERVICE="$2"
      shift 2
      ;;
    --migrate-job)
      MIGRATE_JOB="$2"
      shift 2
      ;;
    --run-sa)
      RUN_SA="$2"
      shift 2
      ;;
    --cloudsql-instance)
      CLOUDSQL_INSTANCE="$2"
      shift 2
      ;;
    --db-name)
      DB_NAME="$2"
      shift 2
      ;;
    --db-user)
      DB_USER="$2"
      shift 2
      ;;
    --db-password-secret)
      DB_PASSWORD_SECRET="$2"
      shift 2
      ;;
    --cloud-tasks-queue)
      CLOUD_TASKS_QUEUE_NAME="$2"
      shift 2
      ;;
    --cloud-tasks-invoker-sa)
      CLOUD_TASKS_INVOKER_SA="$2"
      shift 2
      ;;
    --illustration-bucket)
      ILLUSTRATION_BUCKET="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --allowed-origins)
      ALLOWED_ORIGINS="$2"
      shift 2
      ;;
    --base-url)
      BASE_URL_OVERRIDE="$2"
      shift 2
      ;;
    --internal-service-url)
      INTERNAL_SERVICE_URL_OVERRIDE="$2"
      shift 2
      ;;
    --environment-tag-value-id)
      ENVIRONMENT_TAG_VALUE_ID="$2"
      shift 2
      ;;
    --org-id)
      ORG_ID="$2"
      shift 2
      ;;
    --environment-tag-short-name)
      ENVIRONMENT_TAG_SHORT_NAME="$2"
      shift 2
      ;;
    --skip-project-env-tag)
      SKIP_PROJECT_ENV_TAG="1"
      shift 1
      ;;
    --dylen-env)
      DYLEN_ENV_VALUE="$2"
      shift 2
      ;;
    --tag)
      TAG="$2"
      shift 2
      ;;
    --allow-unknown-env)
      ALLOW_UNKNOWN_ENV="1"
      shift 1
      ;;
    --skip-secrets-stage)
      SKIP_SECRETS_STAGE="1"
      shift 1
      ;;
    --skip-dsn-secret-update)
      SKIP_DSN_SECRET_UPDATE="1"
      shift 1
      ;;
    --skip-firebase-sa-setup)
      SKIP_FIREBASE_SA_SETUP="1"
      shift 1
      ;;
    --skip-cloud-tasks-setup)
      SKIP_CLOUD_TASKS_SETUP="1"
      shift 1
      ;;
    --skip-storage-setup)
      SKIP_STORAGE_SETUP="1"
      shift 1
      ;;
    --skip-env-sync)
      SKIP_ENV_SYNC="1"
      shift 1
      ;;
    --skip-secret-sync)
      SKIP_SECRET_SYNC="1"
      shift 1
      ;;
    --skip-auth-login)
      SKIP_AUTH_LOGIN="1"
      shift 1
      ;;
    --skip-health-check)
      SKIP_HEALTH_CHECK="1"
      shift 1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$ENV_FILE" ]]; then
  echo "Missing required argument: ENV_FILE" >&2
  usage
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Env file not found: $ENV_FILE" >&2
  exit 1
fi

read_env_var() {
  local file="$1"
  local key="$2"
  local raw_line=""
  raw_line="$(awk -F= -v k="$key" '$1==k {print substr($0, index($0,"=")+1); exit}' "$file")"
  if [[ -z "$raw_line" ]]; then
    return 1
  fi
  raw_line="${raw_line%$'\r'}"
  if [[ "$raw_line" == \"*\" && "$raw_line" == *\" ]]; then
    raw_line="${raw_line#\"}"
    raw_line="${raw_line%\"}"
  elif [[ "$raw_line" == \'*\' && "$raw_line" == *\' ]]; then
    raw_line="${raw_line#\'}"
    raw_line="${raw_line%\'}"
  fi
  printf '%s' "$raw_line"
}

if [[ -z "$PROJECT_ID" ]]; then PROJECT_ID="$(read_env_var "$ENV_FILE" "DEPLOY_PROJECT_ID" || true)"; fi
if [[ -z "$REGION" ]]; then REGION="$(read_env_var "$ENV_FILE" "DEPLOY_REGION" || true)"; fi
if [[ -z "$AR_REPO" ]]; then AR_REPO="$(read_env_var "$ENV_FILE" "DEPLOY_AR_REPO" || true)"; fi
if [[ -z "$IMAGE" ]]; then IMAGE="$(read_env_var "$ENV_FILE" "DEPLOY_IMAGE" || true)"; fi
if [[ -z "$SERVICE" ]]; then SERVICE="$(read_env_var "$ENV_FILE" "DEPLOY_SERVICE" || true)"; fi
if [[ -z "$MIGRATE_JOB" ]]; then MIGRATE_JOB="$(read_env_var "$ENV_FILE" "DEPLOY_MIGRATE_JOB" || true)"; fi
if [[ -z "$RUN_SA" ]]; then RUN_SA="$(read_env_var "$ENV_FILE" "DEPLOY_RUN_SA" || true)"; fi
if [[ -z "$CLOUDSQL_INSTANCE" ]]; then CLOUDSQL_INSTANCE="$(read_env_var "$ENV_FILE" "DEPLOY_CLOUDSQL_INSTANCE" || true)"; fi
if [[ -z "$DB_NAME" ]]; then DB_NAME="$(read_env_var "$ENV_FILE" "DEPLOY_DB_NAME" || true)"; fi
if [[ -z "$DB_USER" ]]; then DB_USER="$(read_env_var "$ENV_FILE" "DEPLOY_DB_USER" || true)"; fi
if [[ -z "$DB_PASSWORD_SECRET" ]]; then DB_PASSWORD_SECRET="$(read_env_var "$ENV_FILE" "DEPLOY_DB_PASSWORD_SECRET" || true)"; fi
if [[ -z "$DB_PASSWORD_SECRET" ]]; then DB_PASSWORD_SECRET="STAGE_DB_PASSWORD"; fi
if [[ -z "$CLOUD_TASKS_QUEUE_NAME" ]]; then CLOUD_TASKS_QUEUE_NAME="$(read_env_var "$ENV_FILE" "DEPLOY_CLOUD_TASKS_QUEUE_NAME" || true)"; fi
if [[ -z "$CLOUD_TASKS_QUEUE_NAME" ]]; then CLOUD_TASKS_QUEUE_NAME="dylen-jobs-queue"; fi
if [[ -z "$CLOUD_TASKS_INVOKER_SA" ]]; then CLOUD_TASKS_INVOKER_SA="$(read_env_var "$ENV_FILE" "DEPLOY_CLOUD_TASKS_INVOKER_SA" || true)"; fi
if [[ -z "$CLOUD_TASKS_INVOKER_SA" ]]; then CLOUD_TASKS_INVOKER_SA="$(read_env_var "$ENV_FILE" "DYLEN_CLOUD_RUN_INVOKER_SERVICE_ACCOUNT" || true)"; fi
if [[ -z "$ILLUSTRATION_BUCKET" ]]; then ILLUSTRATION_BUCKET="$(read_env_var "$ENV_FILE" "DEPLOY_ILLUSTRATION_BUCKET" || true)"; fi
if [[ -z "$ILLUSTRATION_BUCKET" ]]; then ILLUSTRATION_BUCKET="$(read_env_var "$ENV_FILE" "DYLEN_ILLUSTRATION_BUCKET" || true)"; fi
if [[ -z "$ALLOWED_ORIGINS" ]]; then ALLOWED_ORIGINS="$(read_env_var "$ENV_FILE" "DYLEN_ALLOWED_ORIGINS" || true)"; fi
if [[ -z "$BASE_URL_OVERRIDE" ]]; then BASE_URL_OVERRIDE="$(read_env_var "$ENV_FILE" "DYLEN_BASE_URL" || true)"; fi
if [[ -z "$INTERNAL_SERVICE_URL_OVERRIDE" ]]; then INTERNAL_SERVICE_URL_OVERRIDE="$(read_env_var "$ENV_FILE" "DYLEN_INTERNAL_SERVICE_URL" || true)"; fi
if [[ -z "$DYLEN_ENV_VALUE" ]]; then DYLEN_ENV_VALUE="$(read_env_var "$ENV_FILE" "DYLEN_ENV" || true)"; fi
if [[ -z "$DYLEN_ENV_VALUE" ]]; then DYLEN_ENV_VALUE="stage"; fi
if [[ -z "$TAG" ]]; then TAG="$(read_env_var "$ENV_FILE" "DEPLOY_TAG" || true)"; fi
if [[ -z "$TAG" ]]; then TAG="$(git rev-parse --short=12 HEAD)"; fi

required_args=(
  "PROJECT_ID:$PROJECT_ID"
  "REGION:$REGION"
  "AR_REPO:$AR_REPO"
  "IMAGE:$IMAGE"
  "SERVICE:$SERVICE"
  "MIGRATE_JOB:$MIGRATE_JOB"
  "RUN_SA:$RUN_SA"
  "CLOUDSQL_INSTANCE:$CLOUDSQL_INSTANCE"
  "DB_NAME:$DB_NAME"
  "DB_USER:$DB_USER"
  "DB_PASSWORD_SECRET:$DB_PASSWORD_SECRET"
  "CLOUD_TASKS_QUEUE_NAME:$CLOUD_TASKS_QUEUE_NAME"
  "ILLUSTRATION_BUCKET:$ILLUSTRATION_BUCKET"
)

for kv in "${required_args[@]}"; do
  key="${kv%%:*}"
  value="${kv#*:}"
  if [[ -z "$value" ]]; then
    echo "Missing required deploy value: $key" >&2
    echo "Provide it via CLI flag or set DEPLOY_* in $ENV_FILE." >&2
    usage
    exit 1
  fi
done

log_step() {
  echo ""
  echo "============================================================"
  echo "STEP: $1"
  echo "============================================================"
}

run_cmd() {
  echo "+ $*"
  "$@"
}

log_step "Print deployment inputs"
echo "PROJECT_ID=$PROJECT_ID"
echo "REGION=$REGION"
echo "AR_REPO=$AR_REPO"
echo "IMAGE=$IMAGE"
echo "SERVICE=$SERVICE"
echo "MIGRATE_JOB=$MIGRATE_JOB"
echo "RUN_SA=$RUN_SA"
echo "CLOUDSQL_INSTANCE=$CLOUDSQL_INSTANCE"
echo "ENV_FILE=$ENV_FILE"
echo "DB_NAME=$DB_NAME"
echo "DB_USER=$DB_USER"
echo "DB_PASSWORD_SECRET=$DB_PASSWORD_SECRET"
echo "CLOUD_TASKS_QUEUE_NAME=$CLOUD_TASKS_QUEUE_NAME"
echo "CLOUD_TASKS_INVOKER_SA=${CLOUD_TASKS_INVOKER_SA:-<not_set>}"
echo "ILLUSTRATION_BUCKET=$ILLUSTRATION_BUCKET"
echo "ALLOWED_ORIGINS=${ALLOWED_ORIGINS:-<not_overridden>}"
echo "BASE_URL_OVERRIDE=${BASE_URL_OVERRIDE:-<auto>}"
echo "INTERNAL_SERVICE_URL_OVERRIDE=${INTERNAL_SERVICE_URL_OVERRIDE:-<auto>}"
echo "DYLEN_ENV_VALUE=$DYLEN_ENV_VALUE"
echo "ENVIRONMENT_TAG_VALUE_ID=${ENVIRONMENT_TAG_VALUE_ID:-<resolve_from_org>}"
echo "ORG_ID=${ORG_ID:-<not_set>}"
echo "ENVIRONMENT_TAG_SHORT_NAME=$ENVIRONMENT_TAG_SHORT_NAME"
echo "SKIP_PROJECT_ENV_TAG=$SKIP_PROJECT_ENV_TAG"
echo "TAG=$TAG"
echo "SKIP_SECRET_SYNC=$SKIP_SECRET_SYNC"
echo "SKIP_ENV_SYNC=$SKIP_ENV_SYNC"
echo "SKIP_SECRETS_STAGE=$SKIP_SECRETS_STAGE"
echo "SKIP_DSN_SECRET_UPDATE=$SKIP_DSN_SECRET_UPDATE"
echo "SKIP_FIREBASE_SA_SETUP=$SKIP_FIREBASE_SA_SETUP"
echo "SKIP_CLOUD_TASKS_SETUP=$SKIP_CLOUD_TASKS_SETUP"
echo "SKIP_STORAGE_SETUP=$SKIP_STORAGE_SETUP"
echo "SKIP_AUTH_LOGIN=$SKIP_AUTH_LOGIN"
echo "SKIP_HEALTH_CHECK=$SKIP_HEALTH_CHECK"
echo "ALLOW_UNKNOWN_ENV=$ALLOW_UNKNOWN_ENV"

upsert_env_var() {
  local file="$1"
  local key="$2"
  local value="$3"
  local tmp_file
  if [[ ! -f "$file" ]]; then
    touch "$file"
  fi
  tmp_file="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { replaced = 0 }
    $0 ~ ("^" k "=") && replaced == 0 {
      print k "=" v
      replaced = 1
      next
    }
    { print }
    END {
      if (replaced == 0) {
        print k "=" v
      }
    }
  ' "$file" > "$tmp_file"
  mv "$tmp_file" "$file"
}

upsert_secret_value() {
  local project_id="$1"
  local secret_name="$2"
  local secret_value="$3"

  if ! gcloud secrets describe "$secret_name" --project "$project_id" >/dev/null 2>&1; then
    run_cmd gcloud secrets create "$secret_name" --project "$project_id" --replication-policy automatic
  fi

  echo "+ gcloud secrets versions add $secret_name --project $project_id --data-file=-"
  printf '%s' "$secret_value" | gcloud secrets versions add "$secret_name" --project "$project_id" --data-file=-
}

if [[ "$SKIP_AUTH_LOGIN" != "1" ]]; then
  log_step "Authenticate gcloud account (interactive if needed)"
  run_cmd gcloud auth login
fi

log_step "Set active gcloud project"
run_cmd gcloud config set project "$PROJECT_ID"

if [[ "$SKIP_FIREBASE_SA_SETUP" != "1" ]]; then
  log_step "Ensure Firebase APIs and runtime service-account permissions"
  # Enable Firebase/Auth APIs required by firebase_admin identity lookups in migration bootstrap.
  run_cmd gcloud services enable identitytoolkit.googleapis.com firebase.googleapis.com --project "$PROJECT_ID"
  # Grant Cloud Run runtime SA permission to lookup/create users and set custom claims.
  run_cmd gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${RUN_SA}" --role "roles/firebaseauth.admin"
else
  log_step "Skip Firebase service-account setup (requested)"
fi

if [[ "$SKIP_CLOUD_TASKS_SETUP" != "1" ]]; then
  log_step "Ensure Cloud Tasks queue + enqueuer permissions"
  run_cmd gcloud services enable cloudtasks.googleapis.com --project "$PROJECT_ID"
  if gcloud tasks queues describe "$CLOUD_TASKS_QUEUE_NAME" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
    echo "Cloud Tasks queue already exists: $CLOUD_TASKS_QUEUE_NAME"
  else
    run_cmd gcloud tasks queues create "$CLOUD_TASKS_QUEUE_NAME" --location "$REGION" --project "$PROJECT_ID"
  fi
  run_cmd gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${RUN_SA}" --role "roles/cloudtasks.enqueuer"
  if [[ -n "$CLOUD_TASKS_INVOKER_SA" ]]; then
    # Allow runtime SA to mint OIDC tokens as the configured invoker identity.
    run_cmd gcloud iam service-accounts add-iam-policy-binding "$CLOUD_TASKS_INVOKER_SA" --project "$PROJECT_ID" --member "serviceAccount:${RUN_SA}" --role "roles/iam.serviceAccountUser"
  fi
else
  log_step "Skip Cloud Tasks setup (requested)"
fi

if [[ "$SKIP_STORAGE_SETUP" != "1" ]]; then
  log_step "Ensure illustration bucket exists + runtime SA has access"
  if gcloud storage buckets describe "gs://${ILLUSTRATION_BUCKET}" --project "$PROJECT_ID" >/dev/null 2>&1; then
    echo "Illustration bucket already exists: gs://${ILLUSTRATION_BUCKET}"
  else
    run_cmd gcloud storage buckets create "gs://${ILLUSTRATION_BUCKET}" --project "$PROJECT_ID" --location "$REGION" --uniform-bucket-level-access
  fi
  # Ensure runtime SA can upload/download illustration assets.
  run_cmd gcloud storage buckets add-iam-policy-binding "gs://${ILLUSTRATION_BUCKET}" --member "serviceAccount:${RUN_SA}" --role "roles/storage.objectAdmin" --project "$PROJECT_ID"
else
  log_step "Skip storage setup (requested)"
fi

log_step "Build Cloud SQL DSN from password secret and write into env file"
# Read the DB password from Secret Manager and URL-encode it to safely build a DSN.
DB_PASSWORD_RAW="$(gcloud secrets versions access latest --secret "$DB_PASSWORD_SECRET" --project "$PROJECT_ID")"
if [[ -z "$DB_PASSWORD_RAW" ]]; then
  echo "Secret $DB_PASSWORD_SECRET is empty. Cannot build DYLEN_PG_DSN." >&2
  exit 1
fi
DB_PASSWORD_ENCODED="$(printf '%s' "$DB_PASSWORD_RAW" | python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=""))')"
DYLEN_PG_DSN_VALUE="postgresql://${DB_USER}:${DB_PASSWORD_ENCODED}@/${DB_NAME}?host=/cloudsql/${CLOUDSQL_INSTANCE}"
DYLEN_CLOUD_TASKS_QUEUE_PATH_VALUE="projects/${PROJECT_ID}/locations/${REGION}/queues/${CLOUD_TASKS_QUEUE_NAME}"
# Prefer direct Cloud Run URL for internal task callbacks; edge/CDN front doors can block task delivery.
existing_service_url="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)' 2>/dev/null || true)"
if [[ -z "$BASE_URL_OVERRIDE" ]]; then
  echo "Missing base URL. Set DYLEN_BASE_URL in $ENV_FILE or pass --base-url." >&2
  exit 1
fi
DYLEN_BASE_URL_VALUE="$BASE_URL_OVERRIDE"

if [[ -n "$INTERNAL_SERVICE_URL_OVERRIDE" ]]; then
  DYLEN_INTERNAL_SERVICE_URL_VALUE="$INTERNAL_SERVICE_URL_OVERRIDE"
elif [[ -n "$existing_service_url" ]]; then
  DYLEN_INTERNAL_SERVICE_URL_VALUE="$existing_service_url"
else
  echo "Missing internal service URL. Ensure Cloud Run service exists or pass --internal-service-url." >&2
  exit 1
fi
upsert_env_var "$ENV_FILE" "DYLEN_PG_DSN" "$DYLEN_PG_DSN_VALUE"
upsert_env_var "$ENV_FILE" "DYLEN_TASK_SERVICE_PROVIDER" "gcp"
upsert_env_var "$ENV_FILE" "DYLEN_CLOUD_TASKS_QUEUE_PATH" "$DYLEN_CLOUD_TASKS_QUEUE_PATH_VALUE"
upsert_env_var "$ENV_FILE" "DYLEN_BASE_URL" "$DYLEN_BASE_URL_VALUE"
upsert_env_var "$ENV_FILE" "DYLEN_INTERNAL_SERVICE_URL" "$DYLEN_INTERNAL_SERVICE_URL_VALUE"
if [[ -n "$CLOUD_TASKS_INVOKER_SA" ]]; then
  upsert_env_var "$ENV_FILE" "DYLEN_CLOUD_RUN_INVOKER_SERVICE_ACCOUNT" "$CLOUD_TASKS_INVOKER_SA"
fi
# Ensure task secret exists locally; generate once when missing to avoid weak or empty auth.
DYLEN_TASK_SECRET_VALUE="$(read_env_var "$ENV_FILE" "DYLEN_TASK_SECRET" || true)"
if [[ -z "$DYLEN_TASK_SECRET_VALUE" ]]; then
  DYLEN_TASK_SECRET_VALUE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  upsert_env_var "$ENV_FILE" "DYLEN_TASK_SECRET" "$DYLEN_TASK_SECRET_VALUE"
  echo "Generated DYLEN_TASK_SECRET in $ENV_FILE"
fi
echo "Updated DYLEN_PG_DSN in $ENV_FILE from Secret Manager input."

if [[ "$SKIP_PROJECT_ENV_TAG" != "1" ]]; then
  log_step "Ensure project has required environment tag"
  project_number="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
  if [[ -z "$project_number" ]]; then
    echo "Failed to resolve project number for $PROJECT_ID" >&2
    exit 1
  fi
  parent_ref="//cloudresourcemanager.googleapis.com/projects/${project_number}"

  resolved_tag_value_id="$ENVIRONMENT_TAG_VALUE_ID"
  if [[ -z "$resolved_tag_value_id" ]]; then
    if [[ -z "$ORG_ID" ]]; then
      echo "Project environment tag resolution requires either --environment-tag-value-id or --org-id." >&2
      echo "No tag inputs provided, auto-skipping project environment tag enforcement." >&2
      SKIP_PROJECT_ENV_TAG="1"
    fi

    if [[ "$SKIP_PROJECT_ENV_TAG" != "1" ]]; then
      tag_key_name="$(gcloud resource-manager tags keys list --parent="organizations/${ORG_ID}" --filter='shortName=environment' --format='value(name)' --limit=1)"
      if [[ -z "$tag_key_name" ]]; then
        echo "Could not find tag key shortName=environment under organizations/${ORG_ID}" >&2
        exit 1
      fi

      resolved_tag_value_id="$(gcloud resource-manager tags values list --parent="$tag_key_name" --filter="shortName=${ENVIRONMENT_TAG_SHORT_NAME}" --format='value(name)' --limit=1)"
      if [[ -z "$resolved_tag_value_id" ]]; then
        echo "Could not find tag value shortName=${ENVIRONMENT_TAG_SHORT_NAME} under ${tag_key_name}" >&2
        exit 1
      fi
    fi
  fi

  if [[ "$SKIP_PROJECT_ENV_TAG" != "1" ]]; then
    echo "Using environment tag value: $resolved_tag_value_id"
    if gcloud resource-manager tags bindings list --parent="$parent_ref" --format='value(tagValue)' | grep -qx "$resolved_tag_value_id"; then
      echo "Environment tag already bound to project."
    else
      run_cmd gcloud resource-manager tags bindings create --parent="$parent_ref" --tag-value="$resolved_tag_value_id"
    fi
  else
    log_step "Skip project environment tag enforcement (auto)"
  fi
else
  log_step "Skip project environment tag enforcement (requested)"
fi

log_step "Persist deploy arguments into env file"
upsert_env_var "$ENV_FILE" "DEPLOY_PROJECT_ID" "$PROJECT_ID"
upsert_env_var "$ENV_FILE" "DEPLOY_REGION" "$REGION"
upsert_env_var "$ENV_FILE" "DEPLOY_AR_REPO" "$AR_REPO"
upsert_env_var "$ENV_FILE" "DEPLOY_IMAGE" "$IMAGE"
upsert_env_var "$ENV_FILE" "DEPLOY_SERVICE" "$SERVICE"
upsert_env_var "$ENV_FILE" "DEPLOY_MIGRATE_JOB" "$MIGRATE_JOB"
upsert_env_var "$ENV_FILE" "DEPLOY_RUN_SA" "$RUN_SA"
upsert_env_var "$ENV_FILE" "DEPLOY_CLOUDSQL_INSTANCE" "$CLOUDSQL_INSTANCE"
upsert_env_var "$ENV_FILE" "DEPLOY_DB_NAME" "$DB_NAME"
upsert_env_var "$ENV_FILE" "DEPLOY_DB_USER" "$DB_USER"
upsert_env_var "$ENV_FILE" "DEPLOY_DB_PASSWORD_SECRET" "$DB_PASSWORD_SECRET"
upsert_env_var "$ENV_FILE" "DEPLOY_CLOUD_TASKS_QUEUE_NAME" "$CLOUD_TASKS_QUEUE_NAME"
upsert_env_var "$ENV_FILE" "DEPLOY_CLOUD_TASKS_INVOKER_SA" "$CLOUD_TASKS_INVOKER_SA"
upsert_env_var "$ENV_FILE" "DEPLOY_ILLUSTRATION_BUCKET" "$ILLUSTRATION_BUCKET"
upsert_env_var "$ENV_FILE" "DEPLOY_TAG" "$TAG"
upsert_env_var "$ENV_FILE" "DYLEN_ENV" "$DYLEN_ENV_VALUE"
if [[ -n "$ALLOWED_ORIGINS" ]]; then
  upsert_env_var "$ENV_FILE" "DYLEN_ALLOWED_ORIGINS" "$ALLOWED_ORIGINS"
fi
echo "Updated deploy metadata in $ENV_FILE"

if [[ "$SKIP_DSN_SECRET_UPDATE" != "1" ]]; then
  log_step "Update DYLEN_PG_DSN secret directly from derived value"
  upsert_secret_value "$PROJECT_ID" "DYLEN_PG_DSN" "$DYLEN_PG_DSN_VALUE"
else
  log_step "Skip direct DYLEN_PG_DSN secret update (requested)"
fi

if [[ "$SKIP_SECRETS_STAGE" == "1" ]]; then
  log_step "Update Cloud Tasks secrets directly (secrets stage skipped)"
  upsert_secret_value "$PROJECT_ID" "DYLEN_TASK_SERVICE_PROVIDER" "gcp"
  upsert_secret_value "$PROJECT_ID" "DYLEN_CLOUD_TASKS_QUEUE_PATH" "$DYLEN_CLOUD_TASKS_QUEUE_PATH_VALUE"
  upsert_secret_value "$PROJECT_ID" "DYLEN_BASE_URL" "$DYLEN_BASE_URL_VALUE"
  upsert_secret_value "$PROJECT_ID" "DYLEN_INTERNAL_SERVICE_URL" "$DYLEN_INTERNAL_SERVICE_URL_VALUE"
  upsert_secret_value "$PROJECT_ID" "DYLEN_TASK_SECRET" "$DYLEN_TASK_SECRET_VALUE"
  upsert_secret_value "$PROJECT_ID" "DYLEN_ILLUSTRATION_BUCKET" "$ILLUSTRATION_BUCKET"
  if [[ -n "$CLOUD_TASKS_INVOKER_SA" ]]; then
    upsert_secret_value "$PROJECT_ID" "DYLEN_CLOUD_RUN_INVOKER_SERVICE_ACCOUNT" "$CLOUD_TASKS_INVOKER_SA"
  fi
fi

if [[ "$SKIP_SECRETS_STAGE" == "1" ]]; then
  log_step "Skip all local secret stages (requested)"
elif [[ "$SKIP_ENV_SYNC" == "1" || "$SKIP_SECRET_SYNC" == "1" ]]; then
  log_step "Skip env sync step (requested)"
elif [[ "$SKIP_SECRET_SYNC" != "1" ]]; then
  sync_extra_args=()
  if [[ "$ALLOW_UNKNOWN_ENV" == "1" ]]; then
    sync_extra_args+=(--allow-unknown)
  fi

  log_step "Validate env contract against .env file (dry run)"
  run_cmd uv run python scripts/gcp_sync_env_to_secrets.py --project-id "$PROJECT_ID" --env-file "$ENV_FILE" --target both --default-dylen-env "$DYLEN_ENV_VALUE" --dry-run "${sync_extra_args[@]}"

  log_step "Sync .env values into Secret Manager"
  run_cmd uv run python scripts/gcp_sync_env_to_secrets.py --project-id "$PROJECT_ID" --env-file "$ENV_FILE" --target both --default-dylen-env "$DYLEN_ENV_VALUE" "${sync_extra_args[@]}"
else
  log_step "Skip secret sync (requested)"
fi

if [[ "$SKIP_SECRETS_STAGE" != "1" ]]; then
  log_step "Verify required Secret Manager keys exist"
  # Keep this list aligned with app/core/env_contract.py required service keys.
  required_secret_keys=(
    "DYLEN_ENV"
    "DYLEN_ALLOWED_ORIGINS"
    "DYLEN_PG_DSN"
    "GCP_PROJECT_ID"
    "GCP_LOCATION"
    "FIREBASE_PROJECT_ID"
    "DYLEN_ILLUSTRATION_BUCKET"
    "GEMINI_API_KEY"
    "OPENROUTER_API_KEY"
  )
  for key in "${required_secret_keys[@]}"; do
    run_cmd gcloud secrets describe "$key" --project "$PROJECT_ID" >/dev/null
    echo "OK secret: $key"
  done
fi

if [[ "$SKIP_SECRETS_STAGE" != "1" && -n "$ALLOWED_ORIGINS" ]]; then
  log_step "Override DYLEN_ALLOWED_ORIGINS secret from --allowed-origins"
  echo "+ gcloud secrets versions add DYLEN_ALLOWED_ORIGINS --project $PROJECT_ID --data-file=-"
  printf '%s' "$ALLOWED_ORIGINS" | gcloud secrets versions add DYLEN_ALLOWED_ORIGINS --project "$PROJECT_ID" --data-file=-
fi

log_step "Submit stage Cloud Build deployment"
run_cmd gcloud builds submit \
  --project "$PROJECT_ID" \
  --config cloudbuild-stage.migrate.yml \
  --substitutions "_REGION=$REGION,_AR_REPO=$AR_REPO,_IMAGE=$IMAGE,_TAG=$TAG,_SERVICE=$SERVICE,_MIGRATE_JOB=$MIGRATE_JOB,_RUN_SA=$RUN_SA,_CLOUDSQL_INSTANCE=$CLOUDSQL_INSTANCE,_CLOUD_RUN_INVOKER_SA=$CLOUD_TASKS_INVOKER_SA"

log_step "Resolve stage URL"
STAGE_URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)')"
echo "STAGE_URL=$STAGE_URL"

if [[ "$SKIP_HEALTH_CHECK" != "1" ]]; then
  log_step "Run health check"
  run_cmd curl -fsS "$STAGE_URL/health"
else
  log_step "Skip health check (requested)"
fi

log_step "Show latest service revision + image"
run_cmd gcloud run services describe "$SERVICE" --region "$REGION" --format='yaml(status.latestReadyRevisionName,spec.template.spec.containers[0].image)'

log_step "Show recent migration job executions"
run_cmd gcloud run jobs executions list --job "$MIGRATE_JOB" --region "$REGION" --limit 3

if [[ -n "$CLOUD_TASKS_INVOKER_SA" ]]; then
  log_step "Ensure Cloud Tasks invoker service account can call the service"
  run_cmd gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --member "serviceAccount:${CLOUD_TASKS_INVOKER_SA}" --role "roles/run.invoker"
fi

log_step "Stage deployment finished successfully"
echo "Service URL: $STAGE_URL"
