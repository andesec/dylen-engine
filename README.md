# DGS

Data Generation Service for DLE. A service that uses AI to generate JSON content to be consumed and presented by the DLE.

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

- `DGS_DEV_KEY`: Shared secret required via the `X-DGS-Dev-Key` request header.
- `DGS_ALLOWED_ORIGINS`: Comma-separated list of allowed CORS origins (no `*`).

Provider secrets (required when wiring real providers or deploying with SAM):

- `OPENROUTER_API_KEY`: API key for the OpenRouter provider.
- `GEMINI_API_KEY`: API key for the Gemini provider.

Storage and tuning:

- `DGS_PG_DSN`: Postgres connection string (default: `postgresql://dgs:dgs_password@localhost:5432/dgs`).
- `DGS_MAX_TOPIC_LENGTH`: Max topic length (default: `200`).
- `DGS_GATHERER_PROVIDER`: Provider for the gatherer step (default: `gemini`).
- `DGS_GATHERER_MODEL`: Optional model override for the gatherer step.
- `DGS_STRUCTURER_PROVIDER`: Provider for the structurer step (default: `openrouter`).
- `DGS_STRUCTURER_MODEL`: Default model for the structurer step.
- `DGS_STRUCTURER_MODEL_FAST`: Optional override when `mode=fast`.
- `DGS_STRUCTURER_MODEL_BALANCED`: Optional override when `mode=balanced`.
- `DGS_STRUCTURER_MODEL_BEST`: Optional override when `mode=best`.
- `DGS_PROMPT_VERSION`: Prompt version tag (default: `v1`).
- `DGS_SCHEMA_VERSION`: Schema version tag (default: `1.0`).

## Running locally

Use Uvicorn to serve the FastAPI app with reload enabled:

```bash
cd dgs-backend
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


