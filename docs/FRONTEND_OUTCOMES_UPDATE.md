# Frontend Outcomes UI Update Instructions

## Overview
The outcomes API has been updated with significant improvements:
- **Simplified depth selection**: Replaced `depth` dropdown with `section_count` range slider (1-5)
- **New learning architecture**: Separated learning focus from teaching approach
- **AI-suggested blueprint**: Outcomes response now suggests the best blueprint
- **Freeform teacher persona**: AI generates a specific instructor title
- **Dynamic outcome scaling**: Outcome count now scales with section count (3-8 outcomes)

---

## 1. Update Lesson Catalog Endpoint Response

The `/v1/lessons/catalog` endpoint now returns updated fields:

### Removed Fields
- `depths` (replaced by `section_counts`)
- `teaching_styles` (replaced by `learning_focus` and `teaching_approaches`)

### New Fields
```json
{
  "blueprints": [...],
  "learning_focus": [
    {
      "id": "conceptual",
      "label": "Conceptual",
      "tooltip": "Mental models and intuition; understand how things work and why."
    },
    {
      "id": "applied",
      "label": "Applied",
      "tooltip": "Hands-on application; learn by doing and executing."
    },
    {
      "id": "comprehensive",
      "label": "Comprehensive",
      "tooltip": "Both theory and practice; complete understanding with application."
    }
  ],
  "teaching_approaches": [
    {
      "id": "direct",
      "label": "Direct Instruction",
      "tooltip": "Clear explanations with step-by-step guidance; efficient and structured."
    },
    {
      "id": "socratic",
      "label": "Socratic Questioning",
      "tooltip": "Questions that guide discovery; builds deep reasoning and insight."
    },
    {
      "id": "narrative",
      "label": "Narrative/Storytelling",
      "tooltip": "Stories and context that make concepts memorable and relatable."
    },
    {
      "id": "experiential",
      "label": "Experiential Practice",
      "tooltip": "Learning through doing, reflection, and iteration."
    },
    {
      "id": "adaptive",
      "label": "Adaptive Mix",
      "tooltip": "AI chooses the best approach for each section based on content."
    }
  ],
  "learner_levels": [
    {
      "id": "curious",
      "label": "Curious Explorer",
      "tooltip": "Just starting, no prior experience; gentle introduction to fundamentals."
    },
    {
      "id": "student",
      "label": "Active Student",
      "tooltip": "Learning actively with some familiarity; ready for guided practice."
    },
    {
      "id": "practitioner",
      "label": "Practitioner",
      "tooltip": "Applying knowledge regularly; ready for deeper analysis and nuance."
    },
    {
      "id": "specialist",
      "label": "Specialist",
      "tooltip": "Advanced expertise; focus on optimization, edge cases, and mastery."
    }
  ],
  "section_counts": [
    {
      "id": 1,
      "label": "Quick Overview",
      "tooltip": "Brief introduction to the topic with essential concepts."
    },
    {
      "id": 2,
      "label": "Highlights",
      "tooltip": "Key concepts and takeaways for quick learning."
    },
    {
      "id": 3,
      "label": "Standard",
      "tooltip": "Balanced coverage with core concepts and practice."
    },
    {
      "id": 4,
      "label": "Detailed",
      "tooltip": "Comprehensive exploration with deeper analysis."
    },
    {
      "id": 5,
      "label": "In-Depth",
      "tooltip": "Thorough, extensive coverage with advanced topics."
    }
  ],
  "widgets": [...]
}
```

---

## 2. Update Outcomes Request Form

### Remove These Fields
- `depth` (dropdown with highlights/detailed/training)
- `blueprint` (user-selected blueprint)
- `widgets` (user-selected widgets)

### Add/Update These Fields

#### Section Count (Range Slider)
**Component**: Range Slider (same style as learner level)
- **Field name**: `section_count`
- **Type**: Integer
- **Range**: 1-5
- **Default**: 2
- **Labels**: Use the labels from `section_counts` catalog data
  - 1: "Quick Overview"
  - 2: "Highlights" (default)
  - 3: "Standard"
  - 4: "Detailed"
  - 5: "In-Depth"
- **Display**: Show tooltip on hover for each value
- **Required**: Yes

#### Learning Focus (Single Select)
**Component**: Radio buttons or dropdown
- **Field name**: `learning_focus`
- **Options**: From catalog `learning_focus` array
- **Default**: "comprehensive"
- **Required**: Yes
- **Layout**: Show label and tooltip for each option

#### Teaching Approach (Multi-Select)
**Component**: Checkbox group (max 5 selections)
- **Field name**: `teaching_style` (keep this name for backward compatibility)
- **Options**: From catalog `teaching_approaches` array
- **Default**: ["adaptive"]
- **Min selections**: 1
- **Max selections**: 5
- **Required**: Yes
- **Layout**: Show label and tooltip for each option
- **Note**: "Adaptive" option means AI will choose the best approach per section

#### Learner Level (Single Select - Already Exists)
**Update labels**: Use new labels from catalog
- curious → "Curious Explorer"
- student → "Active Student"
- practitioner → "Practitioner"
- specialist → "Specialist"

---

## 3. Outcomes Request Payload

### POST /v1/lessons/outcomes

**Request Body**:
```json
{
  "topic": "Introduction to Python",
  "details": "Focus on data structures and algorithms",
  "learning_focus": "comprehensive",
  "teaching_style": ["adaptive", "experiential"],
  "learner_level": "student",
  "section_count": 3,
  "lesson_language": "English",
  "secondary_language": null
}
```

**Required Fields**:
- `topic` (1-200 chars)
- `details` (0-300 chars, can be empty string)
- `learning_focus` (one of: conceptual, applied, comprehensive)
- `teaching_style` (array of 1-5 approach IDs)
- `learner_level` (one of: curious, student, practitioner, specialist)
- `section_count` (integer 1-5)
- `lesson_language` (default: "English")

**Optional Fields**:
- `secondary_language` (only for languagepractice blueprint - not user-selected at this stage)

---

## 4. Handle Outcomes Response

### Response Schema

**Success Response**:
```json
{
  "ok": true,
  "error": null,
  "message": null,
  "blocked_category": null,
  "outcomes": [
    "Learner can identify Python's core data structures (lists, dicts, sets, tuples).",
    "Learner can implement basic sorting algorithms (bubble sort, insertion sort).",
    "Learner can analyze time complexity using Big O notation.",
    "Learner can compare performance trade-offs between different data structures.",
    "Learner can apply appropriate data structures to solve real-world problems."
  ],
  "suggested_blueprint": "webdevandcoding",
  "teacher_persona": "Python Core Contributor",
  "suggested_widgets": [
    "asciidiagram",
    "mcqs",
    "table",
    "compare",
    "codeeditor",
    "interactiveterminal",
    "terminaldemo",
    "stepflow",
    "checklist"
  ]
}
```

**Blocked Response**:
```json
{
  "ok": false,
  "error": "TOPIC_NOT_ALLOWED",
  "message": "This topic is not allowed because it contains explicit sexual content. Educational topics like human reproduction, sexual health, and comprehensive sex education are permitted.",
  "blocked_category": "explicit_sexual",
  "outcomes": [],
  "suggested_blueprint": null,
  "teacher_persona": null,
  "suggested_widgets": []
}
```

### Response Fields

- **ok** (boolean): `true` if topic is allowed, `false` if blocked
- **error** (string | null): Error code when blocked (always "TOPIC_NOT_ALLOWED")
- **message** (string | null): Human-readable reason for blocking
- **blocked_category** (string | null): Category of block (explicit_sexual, political_advocacy, military_warfare, invalid_input)
- **outcomes** (array): 3-8 learning outcomes (scales with section_count)
  - 1 section → 3-4 outcomes
  - 2 sections → 4-5 outcomes
  - 3 sections → 5-6 outcomes
  - 4 sections → 6-7 outcomes
  - 5 sections → 7-8 outcomes
- **suggested_blueprint** (string | null): AI-recommended blueprint ID
- **teacher_persona** (string | null): Specific instructor archetype (e.g., "Certified Ethical Hacker", "React Core Contributor")
- **suggested_widgets** (array): Filtered widget list based on suggested blueprint and selected teaching approaches
  - Empty array if topic is blocked
  - Curated list when `ok: true` (e.g., codeEditor/interactiveTerminal for coding topics)
  - Use this list to populate the widget selector in lesson generation UI

---

## 5. Display Outcomes Confirmation

### UI Flow

1. **Show Loading State** during API call
   - Message: "Analyzing topic and generating learning outcomes..."

2. **If Blocked** (`ok: false`)
   - Display error message from `message` field
   - Show icon/styling based on `blocked_category`
   - Allow user to edit topic and retry
   - Do not proceed to lesson generation

3. **If Success** (`ok: true`)
   - Show confirmation dialog/modal with:
     - **Topic**: User's original topic
     - **Outcomes**: Show all outcomes as a bulleted list
     - **Suggested Blueprint**: Display as a badge/chip with label from catalog
       - Example: "Web Dev and Coding" (from `suggested_blueprint: "webdevandcoding"`)
     - **Teacher Persona**: Display prominently
       - Example: "Your instructor: Python Core Contributor"
     - **Section Count**: Remind user of their selection
       - Example: "3 sections (Standard depth)"

### Confirmation Dialog Layout Example

```
┌────────────────────────────────────────────────────┐
│ Learning Outcomes Ready                             │
├────────────────────────────────────────────────────┤
│                                                     │
│ Topic: Introduction to Python                      │
│                                                     │
│ Your Instructor: Python Core Contributor           │
│ Blueprint: Web Dev and Coding                      │
│                                                     │
│ Learning Outcomes (3 sections - Standard):         │
│ • Learner can identify Python's core data ...      │
│ • Learner can implement basic sorting ...          │
│ • Learner can analyze time complexity ...          │
│ • Learner can compare performance ...              │
│ • Learner can apply appropriate data ...           │
│                                                     │
│ [Edit Topic]  [Cancel]  [Generate Lesson →]        │
└────────────────────────────────────────────────────┘
```

### Action Buttons

- **Edit Topic**: Return to outcomes form with fields pre-filled
- **Cancel**: Clear form and start over
- **Generate Lesson**: Proceed to lesson generation with:
  - All outcomes
  - Suggested blueprint (now user can see but not change it in outcomes - it's set by AI)
  - User-selected parameters (learning_focus, teaching_style, learner_level, section_count)

---

## 6. Pass to Lesson Generation

### POST /v1/lessons/generate

The lesson generation endpoint now expects:

```json
{
  "topic": "Introduction to Python",
  "details": "Focus on data structures and algorithms",
  "outcomes": [
    "Learner can identify Python's core data structures...",
    "Learner can implement basic sorting algorithms...",
    "Learner can analyze time complexity...",
    "Learner can compare performance trade-offs...",
    "Learner can apply appropriate data structures..."
  ],
  "blueprint": "webdevandcoding",
  "learning_focus": "comprehensive",
  "teaching_style": ["adaptive", "experiential"],
  "learner_level": "student",
  "section_count": 3,
  "lesson_language": "English",
  "secondary_language": null,
  "widgets": null,
  "idempotency_key": "uuid-v4-here"
}
```

**Key Changes**:
- `blueprint`: Use the `suggested_blueprint` from outcomes response
- `outcomes`: Use the outcomes array from outcomes response
- `section_count`: Use the user-selected section count (not depth)
- `learning_focus`: New field (conceptual/applied/comprehensive)
- `teaching_style`: Changed from old teaching styles to new teaching approaches
- `widgets`: Can be populated from `suggested_widgets` in outcomes response, or left null for all defaults

---

## 7. Backward Compatibility

The API supports legacy requests for backward compatibility:

### Legacy Depth Values
Old clients sending `depth: "highlights"` will be automatically converted:
- "highlights" → section_count: 2
- "detailed" → section_count: 4
- "training" → section_count: 5
- Numeric values (2, 6, 10) also supported and converted

### Legacy Teaching Styles
Old teaching style values still work:
- "conceptual", "theoretical", "practical"
These can be mixed with new values: "direct", "socratic", "narrative", "experiential", "adaptive"

---

## 8. Implementation Checklist

### Phase 1: Update Lesson Catalog Integration
- [ ] Fetch catalog on app load
- [ ] Parse new `learning_focus`, `teaching_approaches`, `learner_levels`, `section_counts` fields
- [ ] Store in state/context for form rendering

### Phase 2: Update Outcomes Request Form
- [ ] Replace depth dropdown with section_count range slider (1-5)
- [ ] Add learning_focus radio/dropdown
- [ ] Replace teaching_style multi-select with new teaching_approaches options
- [ ] Update learner_level labels to new values
- [ ] Remove blueprint and widgets fields from outcomes form
- [ ] Update form validation (all fields except secondary_language required)

### Phase 3: Update Outcomes Request Payload
- [ ] Change `depth` → `section_count` in API call
- [ ] Add `learning_focus` field
- [ ] Update `teaching_style` field with new approach IDs
- [ ] Remove `blueprint` and `widgets` from outcomes request
- [ ] Ensure `details` can be empty string

### Phase 4: Handle Outcomes Response
- [ ] Parse `suggested_blueprint` and map to blueprint label from catalog
- [ ] Display `teacher_persona` prominently
- [ ] Show outcome count scaling (3-8 based on section_count)
- [ ] Handle blocked responses with category-specific styling

### Phase 5: Create Confirmation Dialog
- [ ] Design modal/dialog showing outcomes + suggestions
- [ ] Display suggested blueprint as badge/chip
- [ ] Show teacher persona as instructor title
- [ ] List all outcomes clearly
- [ ] Provide "Edit Topic", "Cancel", "Generate Lesson" actions

### Phase 6: Update Lesson Generation Request
- [ ] Pass `suggested_blueprint` from outcomes to lesson generation
- [ ] Include `section_count` instead of `depth`
- [ ] Add `learning_focus` field
- [ ] Update `teaching_style` with new approach IDs
- [ ] Keep `outcomes` array from outcomes response

### Phase 7: Testing
- [ ] Test all section_count values (1-5) generate appropriate outcome counts
- [ ] Test all learning_focus options
- [ ] Test multi-select teaching approaches (1-5 selections)
- [ ] Test content blocking categories
- [ ] Test suggested blueprint mapping
- [ ] Test teacher persona display
- [ ] Test backward compatibility with legacy clients

---

## 9. UI/UX Recommendations

### Section Count Slider
- Use the same component style as learner level slider
- Show label above current value (e.g., "Standard" for value 3)
- Display tooltip with description on hover
- Consider showing outcome count range hint (e.g., "3 sections: 5-6 outcomes")

### Learning Focus
- Use radio buttons for single selection clarity
- Show tooltips to explain conceptual vs applied vs comprehensive
- Default to "comprehensive" for best overall experience

### Teaching Approach
- Use checkbox group for multi-select
- Clearly indicate "Adaptive" means AI will choose per section
- Limit to 5 selections maximum
- Default to ["adaptive"] for simplicity

### Suggested Blueprint Display
- Show as a badge or chip with icon
- Use blueprint colors/styling from existing blueprint system
- Make it clear this was AI-suggested (not user-selected)
- Allow user to see what blueprint means (show tooltip from catalog)

### Teacher Persona
- Display prominently as "Your Instructor: [Persona]"
- Use distinct typography or styling
- Consider showing an icon or avatar placeholder
- Make it feel personalized and engaging

### Outcomes List
- Use bulleted list for clarity
- Truncate long outcomes with "..." and expand on click/hover
- Show count badge (e.g., "5 outcomes" at the top)
- Consider showing proficiency level tag for each outcome

---

## 10. Error Handling

### Validation Errors
- Ensure all required fields are filled before submitting
- Show inline validation errors
- Highlight missing or invalid fields

### API Errors
- Handle network failures gracefully
- Show retry option for transient failures
- Display clear error messages for validation failures

### Content Blocking
- Show empathetic error messages from API
- Explain why content was blocked
- Suggest how to rephrase or adjust topic
- Allow immediate retry without losing other form data

---

## Questions or Clarifications?

Contact the backend team if you encounter:
- Unexpected response formats
- Missing catalog data
- Validation errors
- Backward compatibility issues

---

**Document Version**: 1.0  
**Last Updated**: February 15, 2026  
**API Version**: Compatible with dylen-engine main branch
