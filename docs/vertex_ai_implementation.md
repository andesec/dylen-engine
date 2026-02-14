# Vertex AI Gemini Implementation Specification

## 1. Executive Summary
This document specifies the technical implementation for adding Google Vertex AI as an LLM provider to the Dylen Engine. This enables enterprise-grade features, regional data residency, and IAM-based security, replacing the API-key-based AI Studio implementation for production use cases.

## 2. Technical Architecture

### 2.1. New Provider Component
A new file `app/ai/providers/vertex_ai.py` will be created. It will utilize the `google-genai` SDK with `vertexai=True`.

**Class Structure:**
*   `VertexAIProvider` (implements `Provider`): Factory for models, manages GCP config.
*   `VertexAIModel` (implements `AIModel`): Handles generation requests using the initialized client.

### 2.2. Configuration Management (`app/config.py`)
New environment variables will be added to the `Settings` class to support Google Cloud configuration.

**New Environment Variables:**
*   `GCP_PROJECT_ID`: (Required for Vertex AI) The Google Cloud Project ID.
*   `GCP_LOCATION`: (Required for Vertex AI) The region (e.g., `us-central1`, `europe-west3`).

### 2.3. Provider Routing (`app/ai/router.py`)
The `ProviderMode` enum will be expanded to include `VERTEXAI`. The `get_provider_for_mode` factory will be updated to instantiate `VertexAIProvider`.

## 3. Implementation Details

### 3.1. File: `app/ai/providers/vertex_ai.py` (New)
```python
import logging
import os
from typing import Any, Final, cast
import warnings
from pydantic.warnings import ArbitraryTypeWarning

# Suppress Pydantic warnings from google-genai
with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=r"<built-in function any> is not a Python type.*",
        category=ArbitraryTypeWarning,
    )
    from google import genai

from app.ai.json_parser import parse_json_with_fallback
from app.ai.providers.base import (
    AIModel,
    ModelResponse,
    Provider,
    SimpleModelResponse,
    StructuredModelResponse,
)

logger = logging.getLogger(__name__)

class VertexAIModel(AIModel):
    def __init__(self, name: str, project: str, location: str) -> None:
        self.name = name
        # Initialize client with Vertex AI engine
        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location
        )
        self.supports_structured_output = True

    async def generate(self, prompt: str) -> ModelResponse:
        # Standard generation implementation
        ...

    async def generate_structured(self, prompt: str, schema: Any) -> StructuredModelResponse:
        # Structured generation implementation
        ...

class VertexAIProvider(Provider):
    _DEFAULT_MODEL: Final[str] = "gemini-2.0-flash"
    _AVAILABLE_MODELS: Final[set[str]] = {
        "gemini-2.0-flash-001",
        "gemini-2.0-flash",
        # ... other supported models
    }

    def __init__(self) -> None:
        self.name = "vertexai"
        self.project_id = os.getenv("GCP_PROJECT_ID")
        self.location = os.getenv("GCP_LOCATION")
        
        if not self.project_id or not self.location:
             raise ValueError("GCP_PROJECT_ID and GCP_LOCATION must be set for Vertex AI provider.")

    def get_model(self, model: str | None = None) -> AIModel:
        model_name = model or self._DEFAULT_MODEL
        # Validation logic...
        return VertexAIModel(model_name, self.project_id, self.location)
```

### 3.2. File: `app/config.py` (Modify)
Add fields to `Settings`:
```python
@dataclass(frozen=True)
class Settings:
    # ... existing fields ...
    gcp_project_id: str | None
    gcp_location: str | None

def get_settings() -> Settings:
    # ...
    return Settings(
        # ...
        gcp_project_id=os.getenv("GCP_PROJECT_ID"),
        gcp_location=os.getenv("GCP_LOCATION"),
    )
```

### 3.3. File: `app/ai/router.py` (Modify)
Update `ProviderMode` and factory:
```python
class ProviderMode(str, Enum):
    GEMINI = "gemini"
    VERTEXAI = "vertexai"  # NEW

def get_provider_for_mode(mode: str | ProviderMode) -> Provider:
    # ...
    if key == ProviderMode.VERTEXAI.value:
        from app.ai.providers.vertex_ai import VertexAIProvider
        return VertexAIProvider()
```

## 4. Security & Authentication
*   **Mechanism**: Application Default Credentials (ADC).
*   **Local Development**: Run `gcloud auth application-default login` to set up local credentials.
*   **Production (Cloud Run)**: Bind a Service Account with `roles/aiplatform.user` directly to the service. No keys to manage.

## 5. Verification Plan
1.  **Unit Tests**: Verify `VertexAIProvider` instantiates correctly when env vars are present, and raises `ValueError` when missing.
2.  **Integration (Manual)**:
    *   Set `GCP_PROJECT_ID` and `GCP_LOCATION`.
### 3.4. Models & Separation
We will define explicit **Vertex-specific model identifiers** to map to the available Vertex AI models (available 2025/2026).

**Vertex AI Models:**
*   **Planner** (Reasoning): `vertex-gemini-2.5-pro`, `vertex-gemini-3.0-pro`
*   **Gatherer** (Knowledge Extraction): `vertex-gemini-2.5-pro` (Default), `vertex-gemini-3.0-pro`
    *   *Note: Using 'Pro' variants only as this agent requires high fidelity for complex extraction. Default is 2.5 pro for stability.*
*   **Structurer** (Content Structuring): `vertex-gemini-2.5-pro` (Default), `vertex-gemini-3.0-pro`
    *   *Note: Using 'Pro' variants only as this agent requires high fidelity for complex structuring. Default is 2.5 pro for stability.*
*   **Repairer** (Coding/Logic): `vertex-gemini-2.5-flash`, `vertex-gemini-3.0-flash`
    *   *Note: Using 'Flash' variants only for fast coding and repair tasks. Pro models are not available for this agent.*

**Implementation Strategy:**
The system will expose these with the `vertex-` prefix. The `VertexAIProvider` will look up the specific engine model ID (e.g. `gemini-3.0-pro`).

**`app/schema/lesson_catalog.py` Updates:**
*   `_GATHERER_MODELS`: Add `vertex-gemini-2.5-pro`, `vertex-gemini-3.0-pro` (no flash variants)
*   `_PLANNER_MODELS`: Add `vertex-gemini-2.5-pro`, `vertex-gemini-3.0-pro` (no flash variants)
*   `_STRUCTURER_MODELS`: Add `vertex-gemini-2.5-pro`, `vertex-gemini-3.0-pro` (no flash variants)
*   `_REPAIRER_MODELS`: Add `vertex-gemini-2.5-flash`, `vertex-gemini-3.0-flash` (no pro variants)
