# Outcomes Agent Prompt Improvements

## Summary

The improved prompt is **significantly shorter and more focused**, emphasizing what we WANT rather than anti-patterns. The agent now suggests the best-fit blueprint and teacher persona, removing the need for upfront widget/blueprint selection.

**Important Changes:**
1. ✅ **Streamlined prompt** - Reduced from ~200 lines to ~100 lines
2. ✅ **Added teacher persona** - LLM assigns ideal instructor archetype
3. ✅ **Blueprint suggestion** - LLM selects best framework instead of user providing it
4. ✅ **Removed widgets** - No longer steers outcomes toward specific interaction types
5. ✅ **Added secondary language** - Context for language-learning topics
6. ✅ **Fixed content moderation** - Distinguishes explicit sexual content from educational sex ed/reproduction

---

## Major Architectural Changes

### 1. **Blueprint Selection (User → AI)**
**Before**: User selects blueprint upfront → passed to outcomes agent  
**After**: AI suggests optimal blueprint based on topic analysis

**Why**: 
- Users often don't know which blueprint fits their topic
- AI can analyze topic and recommend best pedagogical framework
- Reduces cognitive load on frontend selection

**Output example**: `"suggested_blueprint": "knowledge_understanding"`

### 2. **Teacher Persona Assignment (NEW)**
**Before**: No persona guidance  
**After**: AI assigns ideal instructor archetype for the content

**Why**:
- Different topics need different teaching approaches
- Persona guides downstream content generation tone/style
- Examples: "Socratic Professor", "Workshop Facilitator", "Research Scientist"

**Output example**: `"teacher_persona": "Workshop Facilitator"`

### 3. **Widget Removal from Input**
**Before**: Widgets passed to outcomes agent, potentially steering outcomes  
**After**: Widgets removed; outcomes are widget-agnostic

**Why**:
- Outcomes should define WHAT to learn, not HOW to interact
- Prevents circular dependency (outcomes → widgets → outcomes)
- Widget selection should follow outcomes, not precede them

### 4. **Secondary Language Context**
**Before**: Secondary language validated against blueprint  
**After**: Secondary language passed as context; only relevant for language topics

**Why**:
- Simpler validation logic
- Allows AI to determine if topic is language-related
- Explicit note in prompt: "only relevant for language-learning topics; otherwise ignore"

### 5. **Prompt Streamlining (~50% reduction)**
**Before**: ~200 lines with extensive anti-patterns, examples, and verbose guidance  
**After**: ~100 lines focused on positive examples and essential criteria

**Why**:
- Reduces token consumption per request
- Faster inference and lower cost  
- Clearer signal-to-noise ratio for the model
- Focuses on what we WANT, not long lists of what to avoid

---

## Implementation Details

### Content Moderation Fix (CRITICAL)
**Issue**: Previous blocking logic was too broad and would reject legitimate educational topics like human reproduction and sex education.

**Before**: 
- Blocked category: "sexual" → rejected all sexual topics including education
- Would reject: "Human Reproduction", "Sexual Health", "Contraception"

**After**:
- New category: `explicit_sexual` (pornography, adult entertainment)
- Educational topics explicitly allowed
- Messages clarify: "Educational topics like human reproduction, sexual health, and comprehensive sex education are permitted"

### Schema Changes

**OutcomesAgentInput** (removed fields):
- ❌ `blueprint` - AI now suggests this instead
- ❌ `widgets` - Removed to prevent steering outcomes

**OutcomesAgentResponse** (added fields):
- ✅ `suggested_blueprint: str | None` - AI-recommended framework
- ✅ `teacher_persona: str | None` - Ideal instructor archetype

### Prompt Changes

**New prompt structure** ([outcomes_agent_improved.md](app/ai/prompts/outcomes_agent_improved.md)):
1. **Safety Gate** - Concise blocking rules with explicit educational allowlist
2. **Learning Outcomes** - Quality bar with scaffolding guidance (3-6 outcomes)
3. **Blueprint Selection** - Table of 10 blueprints with goals and use cases
4. **Teacher Persona** - 8 archetype options with domain mappings
5. **Inputs** - Streamlined to 7 parameters (removed blueprint, widgets)
6. **Output** - JSON with outcomes + suggested_blueprint + teacher_persona

**Length reduction**: ~200 lines → ~100 lines (~50% smaller)
**Before**: Vague guidance like "avoid trivial outcomes"  
**After**: 5 concrete criteria - Observable, Measurable, Bloom's Level, Realistic Scope, Length

---

## Quality Comparison

### Example Topic: "Newton's Second Law"

#### ❌ Old Response:
```json
{
  "outcomes": [
    "Learner can state Newton's Second Law of Motion.",  // Memorization
    "Learner can identify the components of F=ma.",  // Low-level
    "Learner can apply the formula to solve problems.",  // Vague
    "Learner can calculate force, mass, or acceleration."  // Procedural
  ]
}
```
**Issues**: Memorization-focused, no higher-order thinking, no real-world context.

#### ✅ Improved Response:
```json
{
  "ok": true,
  "outcomes": [
    "Learner can identify the relationship between force, mass, and acceleration in everyday scenarios.",
    "Learner can calculate the force required to accelerate a vehicle using F=ma.",
    "Learner can diagnose why increasing mass decreases acceleration for constant force.",
    "Learner can design an experiment to verify Newton's Second Law using measurable variables."
  ],
  "suggested_blueprint": "knowledge_understanding",
  "teacher_persona": "Research Scientist"
}
```
**Improvements**: Full scaffolding, real-world context, higher-order thinking, measurable actions, blueprint + persona guidance.

---

## Expected Benefits

1. **Better Outcomes Quality**: Action-oriented, measurable, scaffolded progression
2. **Smarter Blueprint Matching**: AI selects best framework based on topic analysis
3. **Pedagogical Guidance**: Teacher persona shapes content generation approach
4. **Reduced Token Cost**: ~50% smaller prompt = lower API costs per request
5. **Legitimate Topics Allowed**: Sexual health, sex ed, and reproduction topics now permitted
6. **Cleaner Architecture**: Widget/blueprint selection decoupled from outcomes generation

---

## Migration Notes

### Code Changes
- ✅ [app/schema/outcomes.py](app/schema/outcomes.py) - Added suggested_blueprint, teacher_persona; removed blueprint, widgets
- ✅ [app/ai/agents/outcomes.py](app/ai/agents/outcomes.py) - Updated prompt rendering to use new template
- ✅ [app/services/outcomes.py](app/services/outcomes.py) - Removed blueprint, widgets from input data  
- ✅ [app/ai/prompts/outcomes_agent_improved.md](app/ai/prompts/outcomes_agent_improved.md) - New streamlined prompt

### Breaking Changes
**API Response Schema Change:**
- Added fields: `suggested_blueprint`, `teacher_persona` (nullable)
- Clients should handle new fields gracefully (they're nullable for backward compat)

**API Request Schema Change:**
- Removed fields: `blueprint`, `widgets` from OutcomesAgentInput
- Existing clients passing these fields will get validation errors
- **Migration path**: Remove blueprint/widgets from outcomes preflight calls

### Backward Compatibility
- Old blocked categories (`sexual`, `political`, `military`) auto-map to new ones
- Validation warnings (not errors) if suggested_blueprint/teacher_persona missing

---

## Testing Recommendations

1. **Safety gate**: Test legitimate sex ed topics ("Human Reproduction", "Contraception")
2. **Blueprint suggestions**: Verify AI selects appropriate frameworks across domains
3. **Teacher personas**: Check persona matches topic type (e.g., "Workshop Facilitator" for skills)
4. **Outcome quality**: Manual review of action verbs, scaffolding, context inclusion
5. **Token usage**: Measure before/after token consumption per request

---

## Next Steps

1. ✅ Code changes implemented
2. ✅ Prompt streamlined
3. ✅ Schema updated with new fields
4. ⬜ Update API clients to handle new response fields
5. ⬜ Update API clients to remove blueprint/widgets from outcomes requests
6. ⬜ Test with sample topics across all blueprint categories
7. ⬜ Deploy to staging and validate outcomes quality
8. ⬜ Monitor token usage reduction
9. ⬜ Graduate to production

