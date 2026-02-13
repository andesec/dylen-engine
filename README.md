# Dylen

Data Generation Service for Dylen. A service that uses AI to generate JSON content to be consumed and presented by the Dylen.

## Prerequisites

- Python 3.11+
- [Make](https://www.gnu.org/software/make/)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) (required for `sam-local`)

## Setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Copy the example environment file and adjust values as needed:

   ```bash
   cp .env.example .env
   ```

3. Install dependencies (including developer tools):

   ```bash
   make install
   ```

## Secrets and environment variables

Store local values in `.env` (never commit it) and pass production secrets through
your deployment system. The app will fail fast if required values are missing.

Required:

- `DYLEN_ALLOWED_ORIGINS`: Comma-separated list of allowed CORS origins (no `*`).

Provider secrets (required when wiring real providers or deploying with SAM):

- `GEMINI_API_KEY`: API key for the Gemini provider.

Storage and tuning:

- `DYLEN_PG_DSN`: Postgres connection string (default: `postgresql://dylen:dylen_password@localhost:5432/dylen`).
- `DYLEN_MAX_TOPIC_LENGTH`: Max topic length (default: `200`).
- `DYLEN_GATHERER_PROVIDER`: Provider for the gatherer step (default: `gemini`).
- `DYLEN_GATHERER_MODEL`: Optional model override for the gatherer step.
- `DYLEN_STRUCTURER_PROVIDER`: Provider for the structurer step (default: `gemini`).
- `DYLEN_STRUCTURER_MODEL`: Default model for the structurer step.
- `DYLEN_STRUCTURER_MODEL_FAST`: Optional override when `mode=fast`.
- `DYLEN_STRUCTURER_MODEL_BALANCED`: Optional override when `mode=balanced`.
- `DYLEN_STRUCTURER_MODEL_BEST`: Optional override when `mode=best`.
- `DYLEN_PROMPT_VERSION`: Prompt version tag (default: `v1`).
- `DYLEN_SCHEMA_VERSION`: Schema version tag (default: `1.0`).

See [docs/database_migrations.md](docs/database_migrations.md) for details on managing database schema changes.

## Running locally

Use Uvicorn to serve the FastAPI app with reload enabled:

```bash
cd dylen-engine
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Alternatively, from the repository root you can run:

```bash
make dev
```

## Quality checks

Run the standard tooling before opening a pull request:

```bash
make format
make lint
make typecheck
make test
```

## Legal

- Privacy Policy: `docs/legal/PRIVACY_POLICY.md`
- Terms of Service: `docs/legal/TERMS_OF_SERVICE.md`
