# Dylen

Data Generation Service for Dylen. A service that uses AI to generate JSON content to be consumed and presented by the Dylen.

## Prerequisites

- Python 3.11+
- [Make](https://www.gnu.org/software/make/)
- [Docker](https://docs.docker.com/get-docker/) for local development and containerization
- [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) (optional, for GCP deployments)

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

Provider secrets (required when wiring real providers or deploying to GCP):

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

## Running the application

### Running with Docker Compose (full stack)

To run the entire application stack in containers (including the app, PostgreSQL, and GCS emulator):

```bash
docker compose up -d --build
```

This configuration:
- Runs the app on port 8002 with HTTPS (requires SSL certificates in `secrets/certs/`)
- Starts PostgreSQL with automatic initialization
- Starts a local GCS emulator for storage testing
- Automatically applies database migrations on startup

Access the application at `https://localhost:8002`.

To view logs:
```bash
docker compose logs -f app
```

To stop and remove containers:
```bash
docker compose down
```

### Debug mode

For debugging with breakpoints (e.g., in PyCharm or VS Code):

```bash
docker compose -f docker-compose.debug.yml up -d --build
./scripts/wait_for_debugger.sh
```

This starts the application in debug mode, allowing you to attach a debugger from your IDE.

### Manual run (advanced)

If you prefer to run the app directly without Docker for the application:

```bash
# Ensure Postgres is running (via Docker)
docker compose up -d postgres postgres-init

# Activate virtual environment
source .venv/bin/activate

# Run with uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

## Quality checks

Run the standard tooling before opening a pull request:

```bash
make format
make lint
make typecheck
make test
```

## Security scanning

The project includes comprehensive security scanning capabilities:

### Software Composition Analysis (SCA)
Scan dependencies for known vulnerabilities:
```bash
make security-sca
```
Requires [Snyk CLI](https://docs.snyk.io/snyk-cli/install-the-snyk-cli) to be installed.

### Static Application Security Testing (SAST)
Run static code analysis for security vulnerabilities:
```bash
make security-sast        # Run both Bandit and Semgrep
make security-sast-bandit # Python-specific security issues
make security-sast-semgrep # Multi-language security patterns
```

### Container Security
Scan the Docker image for vulnerabilities:
```bash
make security-container
```
Requires [Snyk CLI](https://docs.snyk.io/snyk-cli/install-the-snyk-cli) to be installed.

### Dynamic Application Security Testing (DAST)
Run OWASP ZAP security scan against the running application:
```bash
make security-dast
```
This target automatically:
- Creates `.env` from `.env.example` if missing
- Generates self-signed SSL certificates
- Creates dummy service account for testing
- Starts the application with Docker Compose
- Runs OWASP ZAP baseline scan
- Stops the application and cleans up

Results are saved to `reports/zap-report.html` and `reports/zap-report.json`.

### Run all security scans
```bash
make security-all  # Runs SCA, SAST, and Container scans
```

**Note**: All security reports are saved to the `reports/` directory, which is excluded from version control.

## Legal

- Privacy Policy: `docs/legal/PRIVACY_POLICY.md`
- Terms of Service: `docs/legal/TERMS_OF_SERVICE.md`
