# Frontend Specification: Research Agent UI/UX

## Overview
Implement a multi-step research workflow in Svelte that allows users to discover information, vet sources, and synthesize deep reports. The system uses a quota-based model for research actions.

## API Reference

### 1. Discover Sources
**Endpoint:** `POST /v1/research/discover`
**Description:** Performs an initial web search to find candidate sources.
**Cost:** 1 Research Quota

**Request Body:**
```json
{
  "query": "New AI regulations in EU 2025",
  "context": "Focus on generative AI models" // Optional
}
```

**Response:**
```json
{
  "sources": [
    {
      "title": "EU AI Act: first regulation on artificial intelligence",
      "url": "https://www.europarl.europa.eu/topics/en/article/20230601STO93804/eu-ai-act",
      "snippet": "The AI Act is the first-ever comprehensive legal framework on AI..."
    },
    {
      "title": "Artificial Intelligence Act - Wikipedia",
      "url": "https://en.wikipedia.org/wiki/Artificial_Intelligence_Act",
      "snippet": "The Artificial Intelligence Act (AI Act) is a regulation of the European Union..."
    }
  ]
}
```

### 2. Synthesize Report
**Endpoint:** `POST /v1/research/synthesize`
**Description:** Deep crawls selected URLs and generates a cited markdown report.
**Cost:** 0 Quota (Currently bundled with discovery or separate logic, check backend implementation if distinct quota applies. *Note: Backend implementation shows quota is consumed on DISCOVER, synthesis logs but doesn't explicitly consume separate quota in the provided code snippets, but UI should be prepared if it changes. Current code only enforces quota on discover.*)

**Request Body:**
```json
{
  "query": "New AI regulations in EU 2025",
  "urls": [
    "https://www.europarl.europa.eu/topics/en/article/20230601STO93804/eu-ai-act",
    "https://en.wikipedia.org/wiki/Artificial_Intelligence_Act"
  ],
  "user_id": "current-user-uuid" // Note: Backend likely injects this from auth token, check if frontend needs to send it. *Correction: Backend routes/research.py injects user_id from auth token. Frontend sends query and urls only.*
}
```
*Correction on Request Body for Frontend:*
```json
{
  "query": "New AI regulations in EU 2025",
  "urls": [
    "https://www.europarl.europa.eu/topics/en/article/20230601STO93804/eu-ai-act"
  ],
  "user_id": "ignored-by-backend-but-schema-might-require-it"
}
```
*Wait, looking at `ResearchSynthesisRequest` in `app/schema/research.py`, `user_id` is a required field in the Pydantic model. However, in `app/api/routes/research.py`, the route handler takes `ResearchSynthesisRequest`. If the Pydantic model requires it, the frontend MUST send it. But the route injects `current_user`. The route calls `agent.synthesize(..., user_id=str(current_user.id))`. The input `request` (pydantic) still needs to validate. This looks like a potential backend redundancy or the frontend needs to send a dummy or the actual ID. Ideally, the DTO for the API shouldn't require `user_id` if it's auth-derived. But assuming the schema is shared or strict: Frontend should send the user's ID.*

**Response:**
```json
{
  "answer": "# EU AI Act Overview\n\nThe EU AI Act is...\n\nAccording to the European Parliament [1]...",
  "sources": [
    {
      "title": "Source #1",
      "url": "https://www.europarl.europa.eu/topics/en/article/20230601STO93804/eu-ai-act"
    }
  ]
}
```

### 3. Check Quota
**Endpoint:** `GET /api/user/me/quota`
**Description:** Returns the user's current usage and limits.

**Response:**
```json
{
  "tier_name": "Pro",
  "total_research": 50,
  "remaining_research": 42,
  "research_usage_count": 8,
  // ... other quota fields
}
```

## UI/UX Specifications

### 1. UI Components

#### Search Discovery View
*   **Search Bar**:
    *   Input: Text query or pasted URL list.
    *   Action: Triggers `/v1/research/discover`.
    *   State: Disabled while "Searching...".
*   **Source Selection Grid**:
    *   **Cards**: Render `CandidateSource` items.
    *   **Content**: Title, truncated snippet, and a "Source Badge" (e.g., domain extraction like `github.com` -> "GitHub").
    *   **Selection**: Checkboxes. Multi-select.
    *   **Logic**: Pre-select top 3 results automatically.
*   **Action Bar**:
    *   **Primary**: "Synthesize Research" (Enabled only if >= 1 source selected).
    *   **Secondary**: "Add Custom URL" (Input field to manually append a source).

#### Research Response View
*   **Streaming Markdown**: Use a markdown renderer capable of streaming (or simulate if backend is request/response). *Note: Current backend is Request/Response (not streaming).* Show a loading state, then render full markdown.
*   **Citation Tooltips**:
    *   Parse `[1]`, `[2]` in the markdown.
    *   **Hover**: Show tooltip with source title/snippet.
    *   **Click**: Open original URL in new tab.
*   **Source Sidebar**:
    *   Sticky list of "Used Sources" on the right (desktop) or bottom (mobile).
    *   Visual indicator linking citations `[1]` to the sidebar item.

### 2. Workflows

#### Workflow A: The Guided Search
1.  **Input**: User types "Quantum Computing advancements 2024".
2.  **Discovery**:
    *   Frontend calls `/discover`.
    *   Show skeleton loader.
    *   Render "Select Sources" grid.
3.  **Vetting**:
    *   User reviews snippets.
    *   Deselects irrelevant marketing blogs.
    *   Clicks "Synthesize".
4.  **Synthesis**:
    *   Frontend calls `/synthesize`.
    *   Show "Reading & Analyzing..." progress state (5-15s).
    *   Render final Report.

#### Workflow B: Direct Analysis
1.  **Input**: User explicitly provides URLs (detected via regex or "Deep Dive" tab).
2.  **Skip Discovery**: UI bypasses `/discover`.
3.  **Synthesis**: Immediately calls `/synthesize` with provided URLs.

### 3. State Management

**Store Interface:**
```typescript
interface ResearchState {
  query: string;
  context?: string;
  candidates: CandidateSource[];
  selectedUrls: string[];
  report: string | null;
  status: 'idle' | 'searching' | 'vetting' | 'synthesizing' | 'complete' | 'error';
  error?: string;
}
```

### 4. Design Guidelines
*   **Responsive**:
    *   Desktop: Grid layout for sources (3 columns). Sidebar for synthesis sources.
    *   Mobile: Vertical stack for sources. Sources move to bottom drawer in synthesis view.
*   **Interaction**:
    *   Selected cards should have a distinct ring/border (`ring-2 ring-primary`).
    *   Hover effects on cards to encourage vetting.
*   **Loading States**:
    *   **Discovery**: "Scouring the web..."
    *   **Synthesis**: "Reading X sources...", "Extracting key insights...", "Drafting report..." (Rotate messages if >5s).

## Error Handling
*   **Quota Exceeded (403)**:
    *   If `/discover` returns 403: Show "Research Limit Reached" modal. Prompt upgrade.
    *   Check `remaining_research` in quota store before enabling search.
*   **Search Failed (502)**: Show "Search provider unavailable, please try again."
*   **No Sources Found**: Show empty state with "Try a broader query."
