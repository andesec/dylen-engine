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

## Local SAM emulation

To emulate the Lambda/API Gateway locally with SAM, ensure the SAM CLI is installed and then run:

```bash
make sam-local
```

This uses the settings from `.env` to set the stage, log level, and port for the local API Gateway emulator.
