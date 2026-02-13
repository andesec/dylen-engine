# Runtime Configuration Architecture

## Overview

Model configurations are now **database-driven** instead of environment variable-driven. This allows dynamic switching of AI models across tenant/tier/user hierarchies without restarting services.

## Hierarchy of Preference

Configuration is resolved in this order (highest to lowest priority):

```
USER scope override
    ↓ (if not set)
TENANT scope override
    ↓ (if not set)
TIER scope override
    ↓ (if not set)
GLOBAL scope default
    ↓ (if not set)
Hardcoded fallback (in app/services/runtime_config.py)
```

## Key Changes

### Removed
- ❌ Model environment variables: `DYLEN_SECTION_BUILDER_MODEL`, `DYLEN_PLANNER_MODEL`, etc. (from `.env` files)
- ❌ Model fields from `Settings` dataclass (in `app/config.py`)
- ❌ Model-related definitions from `env_contract.py`

### Kept
- ✅ `DYLEN_RESEARCH_SEARCH_MAX_RESULTS` - still env-configurable (not tied to a single model)
- ✅ `DYLEN_ILLUSTRATION_BUCKET` - infrastructure setting
- ✅ All database-backed runtime_config_values

### Added
- ✅ Helper functions in `app/services/runtime_config.py`
- ✅ Runtime config definitions for AI models (`ai.section_builder.model`, `ai.planner.model`, etc.)

## Usage Pattern

### Step 1: Fetch Runtime Config

At request time, fetch the effective configuration:

```python
from app.services.runtime_config import resolve_effective_runtime_config

runtime_config = await resolve_effective_runtime_config(
    session,
    settings=settings,
    org_id=user.org_id,              # Tenant scope
    subscription_tier_id=tier_id,    # Tier scope
    user_id=user_id                  # User scope (optional)
)
```

### Step 2: Use Helper Functions

Use one of the convenience functions to get (provider, model) tuple:

```python
from app.services.runtime_config import get_section_builder_model

provider, model = get_section_builder_model(runtime_config)
# Returns: ("gemini", "gemini-2.5-pro") or user's override

model_instance = get_model_for_mode(provider, model, agent="section_builder")
```

## Available Helper Functions

All helpers follow the same pattern: input `runtime_config` dict, return `(provider, model)` tuple.

```python
# AI Model Helpers
get_section_builder_model(runtime_config)  # planner -> section builder
get_planner_model(runtime_config)          # lesson planning
get_outcomes_model(runtime_config)         # preflight validation
get_repair_model(runtime_config)           # JSON/structure fixing
get_fenster_model(runtime_config)          # widget generation
get_writing_model(runtime_config)          # writing evaluation
get_tutor_model(runtime_config)            # tutoring
get_illustration_model(runtime_config)     # image generation
get_youtube_model(runtime_config)          # YouTube transcription
get_research_model(runtime_config)         # research discovery
get_research_router_model(runtime_config)  # research classification

# Generic Helper
get_model_provider_and_name(
    runtime_config, 
    config_key="ai.section_builder.model",
    default_provider="gemini",
    default_model="gemini-2.5-pro"
)
```

## Database Seeding

Models are stored in `runtime_config_values` table as `"provider/model"` format:

```sql
-- GLOBAL scope (all users default)
INSERT INTO runtime_config_values (key, scope, value_json)
VALUES 
  ('ai.section_builder.model', 'GLOBAL'::runtime_config_scope, '"gemini/gemini-2.5-pro"'),
  ('ai.planner.model', 'GLOBAL'::runtime_config_scope, '"gemini/gemini-2.5-pro"'),
  ('ai.outcomes.model', 'GLOBAL'::runtime_config_scope, '"gemini/gemini-2.5-flash"');

-- TIER scope (different models for premium tier)
INSERT INTO runtime_config_values (key, scope, subscription_tier_id, value_json)
VALUES 
  ('ai.planner.model', 'TIER'::runtime_config_scope, 3, '"gpt-4-turbo"');  -- tier 3 = premium

-- TENANT scope (org-specific override)
INSERT INTO runtime_config_values (key, scope, org_id, value_json)
VALUES 
  ('ai.section_builder.model', 'TENANT'::runtime_config_scope, '...uuid...', '"anthropic/claude-3-sonnet"');
```

## Hardcoded Fallbacks

If no database entry exists at any scope, these fallbacks apply (in `app/services/runtime_config.py`):

```python
"ai.section_builder.model" → "gemini/gemini-2.5-pro"
"ai.planner.model" → "gemini/gemini-2.5-pro"
"ai.outcomes.model" → "gemini/gemini-2.5-flash"
"ai.repair.model" → "gemini/gemini-2.5-flash"
"ai.fenster.model" → "gemini/gemini-2.5-flash"
"ai.writing.model" → "gemini/gemini-2.5-flash"
"ai.tutor.model" → "gemini/gemini-2.5-flash"
"ai.illustration.model" → "gemini/gemini-2.5-flash-image"
"ai.youtube.model" → "gemini/gemini-2.0-flash"
"ai.research.model" → "gemini/gemini-1.5-pro"
"ai.research.router_model" → "gemini/gemini-1.5-flash"
```

## Typical Request Flow

### Before (with env vars + Settings)
```python
@fastapi.post("/lessons")
async def generate_lesson(request: Request, current_user: User, settings: Settings):
    provider = settings.section_builder_provider     # ❌ fixed at startup
    model = settings.section_builder_model            # ❌ fixed at startup
    # Problem: Can't change model without restarting
```

### After (with runtime_config + helpers)
```python
@fastapi.post("/lessons")
async def generate_lesson(request: Request, current_user: User, settings: Settings, db_session: AsyncSession):
    user_tier_id, _ = await get_user_subscription_tier(db_session, current_user.id)
    runtime_config = await resolve_effective_runtime_config(
        db_session,
        settings=settings,
        org_id=current_user.org_id,
        subscription_tier_id=user_tier_id,
        user_id=current_user.id
    )
    provider, model = get_section_builder_model(runtime_config)  # ✅ resolved per-request
    # Advantage: Can override model per-user/tier/org without restart
```

## Format: "provider/model"

All model configs in DB use combined format: `"provider/model"`

**Examples:**
- `"gemini/gemini-2.5-pro"` → Gemini provider, model gemini-2.5-pro
- `"anthropic/claude-3-sonnet"` → Anthropic provider, model claude-3-sonnet
- `"vertexai/vertex-gemini-3.0-pro"` → Vertex AI provider, model vertex-gemini-3.0-pro

Helpers automatically split and handle cases where format is missing (returns default provider).

## Migration Checklist

- [x] Created helper functions in `app/services/runtime_config.py`
- [x] Added `ai.research.model` and `ai.research.router_model` definitions
- [x] Removed model fields from `Settings` dataclass
- [x] Removed model env var parsing from `get_settings()`
- [x] Removed model env vars from `.env` and `.env-stage`
- [x] Removed model definitions from `env_contract.py`
- [ ] **TODO**: Update consuming code to use helpers (Job worker, API routes, AI agents)
- [ ] **TODO**: Seed runtime_config_values with GLOBAL scope models
- [ ] **TODO**: Update deployment docs/scripts

## Benefits

✅ **Dynamic Configuration**: Change models without restarting  
✅ **Multi-tenant Support**: Different models per org/tier  
✅ **Audit Trail**: All model changes logged in DB  
✅ **Rollback Safe**: Easy to revert model config  
✅ **Cleaner Startup**: Fewer env vars to manage  
✅ **Testability**: Mock runtime_config in tests  

## See Also

- [app/services/runtime_config.py](../app/services/runtime_config.py) - Helper functions and core logic
- [app/config.py](../app/config.py) - Settings dataclass (model fields removed)
- [app/core/env_contract.py](../app/core/env_contract.py) - Env var validation (model vars removed)
