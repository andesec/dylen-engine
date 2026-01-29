# Model Providers and Routing

## Overview

The Dylen engine supports three LLM providers, each with distinct models and use cases:

1. **Gemini AI Studio** (`gemini` provider)
2. **Vertex AI** (`vertexai` provider)  
3. **OpenRouter** (`openrouter` provider)

## Provider Distinctions

### Gemini AI Studio vs Vertex AI

**Important**: Gemini AI Studio and Vertex AI are **different services** with different authentication and billing:

| Aspect | Gemini AI Studio | Vertex AI |
|--------|------------------|-----------|
| **Provider** | `gemini` | `vertexai` |
| **Authentication** | API Key (`GEMINI_API_KEY`) | Application Default Credentials (ADC) |
| **Model Prefix** | None (e.g., `gemini-2.5-pro`) | `vertex-` (e.g., `vertex-gemini-2.5-pro`) |
| **Billing** | Gemini AI Studio pricing | Google Cloud Platform pricing |
| **Setup** | API key only | GCP project + ADC setup |
| **Use Case** | Development, quick prototyping | Production, enterprise, data residency |

## Model Naming Convention

### Gemini AI Studio Models
- `gemini-2.5-pro`
- `gemini-2.5-flash`
- `gemini-pro-latest`

### Vertex AI Models
- `vertex-gemini-2.5-pro`
- `vertex-gemini-3.0-pro`
- `vertex-gemini-2.5-flash`
- `vertex-gemini-3.0-flash`

### OpenRouter Models
- `openai/gpt-oss-120b:free`
- `meta-llama/llama-3.1-405b-instruct:free`
- etc.

## Provider Routing Logic

The system automatically routes models to the correct provider based on the model name:

1. **Vertex AI**: Models starting with `vertex-` → `vertexai` provider
2. **Gemini AI Studio**: Models matching known Gemini models → `gemini` provider
3. **OpenRouter**: Models matching known OpenRouter models → `openrouter` provider
4. **Fallback**: Uses the configured default provider for the agent

## Configuration

### Default Configuration (config.py)

```python
# Gatherer
gatherer_provider = "gemini"  # Default provider
gatherer_model = "gemini-2.5-pro"  # Uses Gemini AI Studio

# Structurer  
structurer_provider = "gemini"  # Default provider
structurer_model = "gemini-2.5-pro"  # Uses Gemini AI Studio

# Planner
planner_provider = "openrouter"  # Default provider
planner_model = "openai/gpt-oss-120b:free"  # Uses OpenRouter

# Repairer
repair_provider = "gemini"  # Default provider
repair_model = "google/gemma-3-27b-it:free"  # Uses OpenRouter (auto-routed)
```

### Environment Variables

You can override defaults with environment variables:

```bash
# To use Gemini AI Studio (requires GEMINI_API_KEY)
export DYLEN_PLANNER_PROVIDER="gemini"
export DYLEN_PLANNER_MODEL="gemini-2.5-pro"

# To use Vertex AI (requires GCP_PROJECT_ID, GCP_LOCATION, and ADC)
export DYLEN_PLANNER_PROVIDER="vertexai"
export DYLEN_PLANNER_MODEL="vertex-gemini-2.5-pro"
```

## Switching Between Providers

### Option 1: Model Name (Recommended)

Simply specify the model with the correct prefix:

```python
# Request with Gemini AI Studio
{
  "models": {
    "planner_model": "gemini-2.5-pro"  # Auto-routes to gemini provider
  }
}

# Request with Vertex AI
{
  "models": {
    "planner_model": "vertex-gemini-2.5-pro"  # Auto-routes to vertexai provider
  }
}
```

### Option 2: Explicit Provider (Not Recommended)

You can set the provider explicitly via environment variables, but this is less flexible:

```bash
export DYLEN_PLANNER_PROVIDER="vertexai"
export DYLEN_PLANNER_MODEL="vertex-gemini-2.5-pro"
```

## Troubleshooting

### Error: "Your default credentials were not found"

**Cause**: You're using a Vertex AI model (`vertex-*`) but haven't set up Application Default Credentials.

**Solutions**:
1. **Switch to Gemini AI Studio**: Use `gemini-2.5-pro` instead of `vertex-gemini-2.5-pro`
2. **Set up ADC for Vertex AI**:
   ```bash
   gcloud auth application-default login
   export GCP_PROJECT_ID="your-project-id"
   export GCP_LOCATION="us-central1"
   ```

### Model Routing to Wrong Provider

**Check**:
1. Environment variables (`DYLEN_*_PROVIDER`)
2. Model name prefix (`vertex-` vs no prefix)
3. Model is in the correct enum (`app/api/models.py`)
4. Model is in the correct routing set (`app/services/model_routing.py`)

## Available Models by Agent

### Planner
- **Gemini AI Studio**: `gemini-2.5-pro`, `gemini-pro-latest`
- **Vertex AI**: `vertex-gemini-2.5-pro`, `vertex-gemini-3.0-pro`
- **OpenRouter**: Various free models

### Gatherer
- **Gemini AI Studio**: `gemini-2.5-pro`
- **Vertex AI**: `vertex-gemini-2.5-pro`, `vertex-gemini-3.0-pro`
- **OpenRouter**: Various free models

### Structurer
- **Gemini AI Studio**: `gemini-2.5-pro`
- **Vertex AI**: `vertex-gemini-2.5-pro`, `vertex-gemini-3.0-pro`
- **OpenRouter**: Various free models

### Repairer
- **Gemini AI Studio**: `gemini-2.5-flash`
- **Vertex AI**: `vertex-gemini-2.5-flash`, `vertex-gemini-3.0-flash`
- **OpenRouter**: Various free models
