# Integration Guide: Selective Widget Schemas with Mirascope

## Current Implementation

The existing agents use a schema service to generate selective schemas:

```python
# In section_builder.py (lines 91-103)
if request.widgets:
    allowed_widgets = request.widgets
elif request.blueprint:
    allowed_widgets = get_widget_preference(request.blueprint, request.teaching_style)
else:
    allowed_widgets = None

if allowed_widgets:
    schema = self._schema_service.subset_section_schema(allowed_widgets)
else:
    schema = self._schema_service.section_schema()
```

## Integration Points

### Option 1: Keep Existing Schema Service (Recommended for Now)

The existing `_schema_service.subset_section_schema()` already implements selective widget filtering. **No immediate changes needed** to existing agents.

**Benefits:**
- Existing code continues to work
- Selective schemas already implemented
- Customer widget selection already respected

### Option 2: Migrate to Mirascope (Future Enhancement)

For new agents or future refactoring, use the Mirascope + selective_schema approach:

```python
from mirascope.core import gemini, prompt_template
from app.schema.selective_schema import create_selective_section

# In agent initialization or configuration
allowed_widgets = ['markdown', 'flip', 'tr', 'fillblank', 'table', 'mcqs']
SectionModel = create_selective_section(allowed_widgets)

# Use in Mirascope call
@gemini.call(model="gemini-2.0-flash-exp", response_model=SectionModel)
@prompt_template("...")
def generate_section(...): ...
```

## Key Findings

1. **Widget Selection Already Implemented**
   - `request.widgets` contains customer-selected widgets
   - `get_widget_preference()` determines widgets from blueprint + teaching style
   - Schema service already filters to allowed widgets

2. **Schema Service Location**
   - Need to find `_schema_service` implementation
   - Likely in `app/ai/` or `app/schema/` directory
   - Should verify it uses msgspec models

3. **Structured Output Flow**
   - Line 109-126: Uses `generate_structured(prompt, schema)`
   - Schema is sanitized per provider (line 110)
   - Response validated after generation (line 140-141)

## Recommended Next Steps

1. **Verify Schema Service Implementation**
   - Find `_schema_service.subset_section_schema()` implementation
   - Confirm it uses the new msgspec widget models
   - Ensure Table/Compare payloads are included

2. **Add Mirascope as Optional Alternative**
   - Keep existing schema service for production
   - Add Mirascope examples for new development
   - Document both approaches

3. **Test Selective Schemas**
   - Verify customer widget selection works with new payloads
   - Test Table (2-6 columns) and Compare (2 columns) validation
   - Ensure schema size reduction is working

## Customer Widget Selection Flow

```
User Request
    ↓
request.widgets (explicit) OR request.blueprint + teaching_style
    ↓
allowed_widgets list
    ↓
schema_service.subset_section_schema(allowed_widgets)
    ↓
Filtered schema with only allowed widgets
    ↓
Gemini API call with minimal schema
```

This flow ensures **only customer-selected widgets** are included in the AI call, reducing tokens and preventing unwanted widget types.
