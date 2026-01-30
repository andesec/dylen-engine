#!/bin/sh
set -eu

# Initialize Postgres with optional SQL scripts.
# How/Why: This runs as a one-shot init container so we can keep the Postgres image unmodified and make initialization repeatable in docker-compose.

: "${POSTGRES_HOST:?POSTGRES_HOST is required}"
: "${POSTGRES_PORT:?POSTGRES_PORT is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"

echo "Waiting for Postgres at ${POSTGRES_HOST}:${POSTGRES_PORT} (db=${POSTGRES_DB})..."
while ! PGPASSWORD="${POSTGRES_PASSWORD}" pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; do
  sleep 1
done
echo "Postgres is ready."

# Execute any init scripts mounted into /init (optional).
# How/Why: This keeps initialization declarative; empty directories are allowed so local dev doesn't fail.
if [ -d /init ]; then
  ran_any="0"
  for script in /init/*.sql /init/*.sql.gz; do
    if [ ! -e "${script}" ]; then
      continue
    fi
    ran_any="1"
    echo "Running init script: ${script}"
    if echo "${script}" | grep -qE '\\.sql$'; then
      PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 -f "${script}"
    else
      gzip -dc "${script}" | PGPASSWORD="${POSTGRES_PASSWORD}" psql -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1
    fi
  done
  if [ "${ran_any}" = "0" ]; then
    echo "No init scripts found in /init; skipping."
  fi
else
  echo "/init not mounted; skipping init scripts."
fi

echo "Postgres init complete."
