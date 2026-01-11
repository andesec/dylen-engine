#!/bin/sh
set -euo pipefail

PSQL_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

echo "Waiting for postgres at ${POSTGRES_HOST}:${POSTGRES_PORT}..."

until pg_isready -d "$PSQL_URL" >/dev/null 2>&1; do
  sleep 1
done

echo "Initializing postgres schema..."

schema_version=$(psql "$PSQL_URL" -tAc "SELECT value FROM llm_audit_meta WHERE key = 'schema_version';" 2>/dev/null || true)

if [ "$schema_version" = "2" ]; then
  echo "Postgres schema already initialized (schema_version=2). Skipping."
  exit 0
fi

psql "$PSQL_URL" -v ON_ERROR_STOP=1 -f /init/llm_audit.sql
