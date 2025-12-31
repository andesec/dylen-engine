# DGS Usage and Testing Guide

This guide provides step-by-step instructions for setting up, testing, and using the Data Generation Service (DGS) locally.

## Prerequisites

- **Python 3.11+**
- **uv** or **pip** (uv recommended for faster dependency resolution)
- **AWS CLI** (optional, for DynamoDB Local)
- **Docker** (optional, for DynamoDB Local via docker-compose)

## Local Development Setup

### 1. Clone the Repository

```bash
cd /path/to/your/workspace
git clone <repository-url>
cd dgs
```

### 2. Set Up Virtual Environment

Using uv (recommended):
```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv sync
```

Using pip:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Copy the example file
cp .env.example .env
```

Edit `.env` and configure the following:

```env
# Required: AI Provider API Keys
GEMINI_API_KEY=your_gemini_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here

# Optional: Development server key (for local testing)
DGS_DEV_KEY=local-dev-secret-key

# Optional: DynamoDB configuration (defaults work with DynamoDB Local)
DDB_TABLE=dgs-lessons-local
DDB_REGION=us-east-1
DDB_ENDPOINT_URL=http://localhost:8000

# Optional: AI model configuration
GATHERER_PROVIDER=gemini
GATHERER_MODEL=gemini-1.5-flash
STRUCTURER_PROVIDER=openrouter
STRUCTURER_MODEL=openai/gpt-4o-mini
```

#### Getting API Keys

- **Gemini**: Get a free API key from [Google AI Studio](https://makersuite.google.com/app/apikey)
- **OpenRouter**: Sign up and get a key from [OpenRouter](https://openrouter.ai/keys)

### 4. Set Up DynamoDB Local (Automatic)

The repository includes a `docker-compose.yml` that automatically:
- Starts DynamoDB Local on port 8000
- Creates the `dgs-lessons-local` table if it doesn't exist
- Persists data in the `dynamodb-data/` directory

**Start everything:**
```bash
docker-compose up -d
```

This will:
1. Start DynamoDB Local with health checks
2. Wait for DynamoDB to be ready
3. Automatically create the table if needed

**Verify it's running:**
```bash
# Check services
docker-compose ps

# List tables
aws dynamodb list-tables --endpoint-url http://localhost:8000
```

**Stop:**
```bash
docker-compose down
```

**Note:** The table creation only happens once. On subsequent runs, docker-compose detects the existing table and skips creation.

## Running the Service Locally

### Start the Development Server

```bash
make dev
```

Or manually:
```bash
cd dgs-backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

The API will be available at `http://localhost:8080`.

### Verify the Service

```bash
curl http://localhost:8080/health
```

Expected response:
```json
{"status": "ok"}
```

## Testing the API

### Generate a Lesson

```bash
curl -X POST http://localhost:8080/v1/lessons/generate \
  -H "Content-Type: application/json" \
  -H "X-DGS-Dev-Key: local-dev-secret-key" \
  -d '{
    "topic": "Introduction to Python",
    "prompt": "Focus on lists and loops",
    "config": {
      "model": "openai/gpt-4o-mini",
      "temperature": 0.4,
      "max_output_tokens": 4096,
      "validation_level": "strict",
      "structured_output": true,
      "language": "en"
    }
  }'
```

### Retrieve a Lesson

```bash
curl http://localhost:8080/v1/lessons/{lesson_id} \
  -H "X-DGS-Dev-Key: local-dev-secret-key"
```

Replace `{lesson_id}` with the ID returned from the generation request.

### Validate Lesson JSON

```bash
curl -X POST http://localhost:8080/v1/lessons/validate \
  -H "Content-Type: application/json" \
  -H "X-DGS-Dev-Key: local-dev-secret-key" \
  -d @path/to/lesson.json
```

### Start and Manage Async Jobs

Start a job:

```bash
curl -X POST http://localhost:8080/v1/jobs \
  -H "Content-Type: application/json" \
  -H "X-DGS-Dev-Key: local-dev-secret-key" \
  -d '{
    "topic": "Space exploration basics",
    "prompt": "Highlight safety considerations for students",
    "config": {
      "language": "en"
    }
  }'
```

Check status:

```bash
curl http://localhost:8080/v1/jobs/{jobId} \
  -H "X-DGS-Dev-Key: local-dev-secret-key"
```

Cancel a running job:

```bash
curl -X POST http://localhost:8080/v1/jobs/{jobId}/cancel \
  -H "X-DGS-Dev-Key: local-dev-secret-key"
```

## Running Tests

### Run All Tests

```bash
make test
```

### Run Unit Tests Only

```bash
pytest tests/unit
```

### Run Integration Tests Only

```bash
pytest tests/integration
```

### Run with Coverage

```bash
pytest --cov=dgs_backend tests/
```

## Code Quality

### Format Code

```bash
make format
```

### Lint Code

```bash
make lint
```

### Type Check

```bash
make typecheck
```

### Run All Quality Checks

```bash
make format lint typecheck test
```

## Troubleshooting

### "GEMINI_API_KEY environment variable is required"

Ensure your `.env` file contains a valid Gemini API key and you've loaded it:
```bash
source .env  # Or restart your terminal/IDE
```

### "Structured output is not available for the configured structurer"

This means the structurer model doesn't support JSON mode. Verify you're using a compatible model:
- Gemini: `gemini-1.5-flash`, `gemini-1.5-pro`, `gemini-2.0-flash-exp`
- OpenRouter: Most OpenAI and Anthropic models

### DynamoDB Connection Errors

1. Verify DynamoDB Local is running:
   ```bash
   curl http://localhost:8000
   ```

2. Check the table exists:
   ```bash
   aws dynamodb list-tables --endpoint-url http://localhost:8000
   ```

3. Ensure `DDB_ENDPOINT_URL` in `.env` points to `http://localhost:8000`

### Import Errors

Reinstall dependencies:
```bash
uv sync --reinstall
# or
pip install -e .[dev] --force-reinstall
```

## Advanced Usage

### Using Different AI Models

Edit `.env` to change providers:

```env
# Use Gemini for both steps
GATHERER_PROVIDER=gemini
GATHERER_MODEL=gemini-2.0-flash
STRUCTURER_PROVIDER=gemini
STRUCTURER_MODEL=gemini-2.0-flash

# Or mix providers
GATHERER_PROVIDER=openrouter
GATHERER_MODEL=google/gemini-2.0-flash-exp:free
STRUCTURER_PROVIDER=openrouter
STRUCTURER_MODEL=openai/gpt-4o-mini
```

### Disable Self-Repair

Set `enable_repair=false` in the request:

```bash
curl -X POST http://localhost:8080/v1/lessons/generate \
  -H "Content-Type: application/json" \
  -H "X-DGS-Dev-Key: local-dev-secret-key" \
  -d '{
    "topic": "Machine Learning Basics",
    "enable_repair": false
  }'
```

(Note: You'll need to add this parameter to the API if not already present.)

### Inspecting Generated Lessons

Use `jq` to format JSON output:

```bash
curl http://localhost:8080/v1/lessons/{lesson_id} \
  -H "X-DGS-Dev-Key: local-dev-secret-key" | jq '.'
```

## Manual AI Testing

Since automated tests for AI generation can be costly and flaky, manual verification is often required to ensure schema compliance and prompt effectiveness.

### 1. Verify Schema Enforcement (OpenRouter)

To verify that OpenRouter is correctly receiving and enforcing the JSON schema:

1.  **Configure `.env`**: Set `STRUCTURER_PROVIDER=openrouter` and `STRUCTURER_MODEL=openai/gpt-4o-mini` (or another supported model).
2.  **Trigger Generation**: Run a generation request (see "Generate a Lesson" above).
3.  **Inspect Logs**:
    *   Check the application logs (stdout if running `uvicorn` manually).
    *   Look for the "Structurer" phase logs.
    *   **Verification**: You should see the model outputting strict JSON that matches the schema structure (e.g., correct widget types like `fill_blank` instead of `fill-in-the-blank`).
4.  **Check Database**:
    *   Execute `aws dynamodb scan --table-name dgs-lessons-local --endpoint-url http://localhost:8000`
    *   Inspect the `result_json` column.
    *   Ensure all `required` fields are present.

### 2. Verify Schema Sanitization (Gemini)

To verify that Gemini is receiving the correct schema with `required` fields:

1.  **Configure `.env`**: Set `STRUCTURER_PROVIDER=gemini` and `STRUCTURER_MODEL=gemini-1.5-flash`.
2.  **Trigger Generation**: Run a generation request.
3.  **Inspect Output**:
    *   If the generation succeeds, the schema was accepted.
    *   If you see `400 InvalidArgument`, the schema might be too complex or contain conflicting constraints. Check logs for the exact error message from Google GenAI SDK.
4.  **Verify Required Fields**:
    *   Check the generated JSON for fields that are marked as required in `LessonDocument` (e.g., `version`, `title`, `blocks` array).
    *   If these are missing, the schema enforcement might be too weak or the prompt needs reinforcement.

## Next Steps

- **Phase 2**: Add lesson listing, tagging, and caching
- **Phase 3**: Implement evaluation harness and fine-tuning data collection
- **Phase 4**: Add authentication with AWS Cognito
- **Production Deployment**: Deploy to AWS Lambda using SAM template in `infra/`

For deployment instructions, see [`CI_CD_SETUP.md`](./CI_CD_SETUP.md).
