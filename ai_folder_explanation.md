# AI Module Documentation for DGS

## Overview

The AI module in the DGS (Dynamic Lesson Engine) backend is a sophisticated orchestration system that leverages multiple AI providers to generate interactive lessons. The system is designed with a two-step pipeline approach: **Gatherer** and **Structurer**, with an optional **Repair** phase to ensure valid output.

## Architecture Overview

The AI module follows a modular architecture with the following key components:

- **Providers**: Abstract interfaces for different AI services (Gemini, OpenRouter)
- **Router**: Centralized routing system to select appropriate providers/models
- **Orchestrator**: Main coordination logic for the AI pipeline
- **Prompts**: Template files for different AI agent roles
- **Repair Utilities**: Deterministic and AI-based validation and repair mechanisms

## Core Components

### 1. Base Provider Interface (`providers/base.py`)

The base module defines abstract interfaces that all AI providers must implement:

```python
class AIModel(ABC):
    name: str
    supports_structured_output: bool = False

    @abstractmethod
    async def generate(self, prompt: str) -> ModelResponse:
        """Generate a response for the given prompt."""

    async def generate_structured(self, prompt: str, schema: dict[str, Any]) -> StructuredModelResponse:
        """Generate structured output that conforms to the provided JSON schema."""
```

This interface ensures consistency across different AI providers while allowing for specialized implementations.

### 2. Provider Implementations

#### Gemini Provider (`providers/gemini.py`)

The Gemini provider uses Google's `google-genai` SDK to interact with Gemini models:

```python
class GeminiModel(AIModel):
    def __init__(self, name: str, api_key: str | None = None) -> None:
        self.name: str = name
        self.supports_structured_output = True
        self._client = genai.Client(api_key=api_key)
```

Key features:
- Supports structured output with JSON schema validation
- Tracks token usage for cost estimation
- Handles both text and structured JSON responses

#### OpenRouter Provider (`providers/openrouter.py`)

The OpenRouter provider uses the OpenAI SDK to interact with various models through OpenRouter:

```python
class OpenRouterModel(AIModel):
    def __init__(self, name: str, api_key: str | None = None, base_url: str | None = None) -> None:
        self.name: str = name
        self.supports_structured_output = True
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or "https://openrouter.ai/api/v1",
        )
```

Key features:
- Supports multiple models (GPT-4, Claude, Gemini)
- Uses OpenAI-compatible API format
- Supports structured JSON output

### 3. Provider Router (`router.py`)

The router provides a centralized way to select providers and models:

```python
class ProviderMode(str, Enum):
    GEMINI = "gemini"
    OPENROUTER = "openrouter"

def get_provider_for_mode(mode: str | ProviderMode) -> Provider:
    provider_map: dict[str, Provider] = {
        ProviderMode.GEMINI.value: GeminiProvider(),
        ProviderMode.OPENROUTER.value: OpenRouterProvider(),
    }
    # Returns appropriate provider instance
```

This allows the system to dynamically switch between different AI providers based on configuration.

### 4. AI Pipeline Orchestration (`orchestrator.py`)

The orchestrator is the heart of the AI system, implementing a sophisticated two-step pipeline:

#### The Two-Step Process

1. **Gatherer Phase**: Collects and organizes information about the topic
2. **Structurer Phase**: Converts the gathered information into structured lesson JSON
3. **Repair Phase**: Validates and fixes any structural issues in the output

```python
async def generate_lesson(self, *, topic: str, prompt: str | None = None, ...) -> OrchestrationResult:
    # Step 1: Gatherer
    gatherer_model_instance = get_model_for_mode(self._gatherer_provider, gatherer_model_name)
    gatherer_response = await gatherer_model_instance.generate(gatherer_prompt)
    
    # Step 2: Structurer
    lesson_json = await self._generate_highlights(...)
    
    # Step 3: Validation and Repair
    ok, errors, _ = validate_lesson(lesson_json)
    if not ok and enable_repair:
        # Attempt deterministic repair first
        # Then AI-based repair if needed
```

#### Different Lesson Types

The orchestrator supports three types of lessons:

- **Highlights**: Brief overview lessons
- **Detailed**: Comprehensive lessons with expanded content
- **Training**: Multi-section lessons with structured content

### 5. AI Prompts (`prompts/` directory)

The system uses specialized prompts for different AI agent roles:

#### Gatherer Agent (`prompts/gatherer.md`)
```
You are the GathererAgent for DGS. Your goal is to produce a comprehensive 
Intermediate Data Model (IDM) that serves as the blueprint for an interactive lesson.
```

The gatherer agent focuses on collecting comprehensive information about the topic, organizing it into core concepts, vocabulary, examples, and interactive elements.

#### Structurer Agent (`prompts/structurer.md`)
```
You are the StructurerAgent for DGS. Convert the IDM into the final lesson JSON
that conforms to the schema and allowed widgets. Output JSON only.
```

The structurer agent converts the intermediate data model into properly formatted lesson JSON.

#### Repair Agent (`prompts/repair.md`)
```
You are an expert at fixing invalid DLE lesson JSON.

Your task is to repair a lesson JSON structure that failed validation...
```

The repair agent fixes validation errors in the generated JSON.

### 6. Deterministic Repair (`deterministic_repair.py`)

Before attempting AI-based repair, the system tries deterministic repairs for common structural issues:

```python
def attempt_deterministic_repair(lesson_json: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    repaired = copy.deepcopy(lesson_json)
    
    # Fix missing version
    if "version" not in repaired:
        repaired["version"] = "1.0"
    
    # Fix missing or empty title
    if not repaired.get("title") or not str(repaired.get("title")).strip():
        repaired["title"] = "Untitled Lesson"
    
    # Fix blocks that are not arrays
    if not isinstance(repaired.get("blocks"), list):
        # Normalize block structure
```

This approach reduces the need for expensive AI calls by fixing common structural issues programmatically.

### 7. Schema Sanitization

The system includes sophisticated schema sanitization to ensure compatibility with different AI providers:

```python
def _sanitize_schema_for_gemini(schema: Any) -> Any:
    """
    Sanitize a JSON Schema for Gemini SDK structured output.
    
    The google-genai schema transformer is strict and can crash if it encounters
    non-schema arrays (e.g., `required: ["a", "b"]`) or unexpected primitives.
    """
    # Remove metadata keys (title/description/examples/default/etc.)
    # Drop `required` entirely (validation happens separately)
    # Replace `$ref` nodes with permissive object schema
```

This ensures that complex JSON schemas can be used with AI providers that have strict schema requirements.

## Why This Architecture?

### 1. **Provider Flexibility**
The modular design allows switching between different AI providers (Gemini, OpenRouter) without changing core logic. This provides:
- Cost optimization by choosing the most economical provider
- Redundancy in case one provider is unavailable
- Ability to leverage different strengths of various models

### 2. **Structured Output Support**
The system supports both regular text generation and structured JSON output, which is crucial for generating valid lesson formats that conform to specific schemas.

### 3. **Robust Error Handling**
The three-tier validation approach (deterministic repair → AI repair → fallback) ensures that even if one step fails, the system can still produce usable output.

### 4. **Cost Optimization**
The system tracks token usage and provides cost estimates, allowing for monitoring and optimization of AI usage costs.

### 5. **Scalability**
The modular design allows for easy addition of new providers, prompt templates, and repair strategies as the system evolves.

## How It Works Together

1. **User Request**: A lesson generation request comes in with a topic and optional constraints
2. **Provider Selection**: The router selects appropriate gatherer and structurer providers/models
3. **Gatherer Phase**: The gatherer AI creates an intermediate data model with comprehensive topic information
4. **Structurer Phase**: The structurer AI converts the IDM into properly formatted lesson JSON
5. **Validation**: The system validates the generated JSON against the lesson schema
6. **Repair**: If validation fails, the system attempts deterministic and/or AI-based repairs
7. **Output**: The final validated lesson JSON is returned with usage statistics and cost estimates

This architecture ensures high-quality, valid lesson generation while maintaining flexibility and cost-effectiveness.