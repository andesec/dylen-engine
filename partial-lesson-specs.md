# Partial Lesson Feature (Streaming) - Specifications

## Overview
The goal is to allow users to start consuming a lesson as soon as the first section is available, rather than waiting for the entire lesson to generate. The specific requirement is to support a "Partial Lesson" flow where the Editor hands off a `job_id` (and metadata) to the Viewer, which then polls the background API for updates, appending new sections as they become available. The Section Timer panel in the Viewer must act as the "Job Status" indicator, listing all expected sections (even those not yet generated) with their status.

## Current Flow (Blocking)
1. **Editor**: User clicks "Generate".
2. **Editor**: POST `/v1/jobs`. Receives `job_id`.
3. **Editor**: Polls `/v1/jobs/{job_id}` until `status === 'done'`.
4. **Editor**: UI shows a progress bar / spinner.
5. **Editor**: On success, gets full JSON, saves to `sessionStorage['lesson_json']`.
6. **Editor**: Redirects to `viewer.html` or displays in Preview.

## Proposed Flow (Streaming)
The new flow introduces a "handoff" state.

### 1. Editor Handoff
*   **User Action**: User clicks "Generate".
*   **API Call**: POST `/v1/jobs`.
*   **Response**: `job_id`, `total_steps` (representing total expected sections), and initial metadata.
*   **Logic Change**:
    *   The Editor continues to show the "Loading" progress UI until the **first section** is retrievable.
    *   Once the first block/section is available, the Editor stores the `job_id` and current partial `lesson_json` in **`localStorage`** (Key: `dle_lessons`). *Correction: Use `localStorage` for all persistence to survive browser close.*
    *   Redirect to `viewer.html` with streaming flags.

### 2. Viewer "Streaming Mode"
*   **Initialization**:
    *   On load, check if `dle_mode === 'streaming'` and `job_id` exists.
    *   Initialize the **new** `StreamingManager` class.
    *   Render the existing sections immediately.
    *   **ToC Removal**: The Table of Contents is removed entirely. The **Section Timer Panel** now serves as the navigation/ToC.
    *   **Default Visibility**: Set default visibility mode to **`card`** (not `all`).

### 3. Background Polling (`StreamingManager` Class)
*   **Architecture**: Create a standalone class `StreamingManager` in `assets/streaming-manager.js`.
*   **Responsibility**:
    *   Manage background polling (interval based on `job_id`).
    *   **Validation & Repair**: Each new section JSON chunk must go through `validateJSON` and `repairJSON` (auto-repair) before being merged.
    *   **Merging**: Use `appendJSON` (progressive-json) to merge validated chunks.
    *   **Persistence**: Save the full `lesson_json` to `localStorage` on every update.
    *   **Notifications**:
        *   Trigger a **non-transparent** "New content available" toast.
        *   **Auto-Render Logic**: Only immediately render new content if visibility is set to **`all`**. If set to `card` (default), simply notify or update the Timer Panel without forcibly changing the view.

### 4. Section Timer & Status Panel
*   **Status List**:
    *   Use `total_steps` from the start to list all sections.
    *   **Available Sections**: Use existing styling.
    *   **Generating/Pending Sections**:
        *   Title: "Section N" (or specific title if available in metadata).
        *   Icon: **Spinning Wheel** (loader) to indicate "In Development/Loading".
*   **Cancel Button**:
    *   Add a **Cancel** button to the panel (next to Resume/Reset).
    *   **Tooltip**: "Cancels the lesson generation".
    *   **Action**: Call **POST** `/v1/jobs/{job_id}/cancel`.
    *   **Behavior**:
        *   Stops the `StreamingManager` polling.
        *   Updates UI to show "Canceled".
        *   Button visibility: Hidden if the job is already complete.

### 5. Navigation & History (New)
*   **Table of Contents**: **REMOVE** entirely.
*   **History / Lessons Button**:
    *   **Placement**: Top-right of Viewer (replacing ToC) and a **3rd button** in the Index "Switch" popup.
    *   **Index Popup**: The "Switch" popup on `index.html` will now have: [Editor] [Viewer] **[History]**.
    *   **Icon**: A new, premium SVG icon (e.g., folder/history style).
    *   **Functionality**:
        *   Opens a popup listing lessons stored in `localStorage`.
        *   **List Item**: Title, timestamp, Status (Complete / Incomplete / Streaming).
        *   **Action**: Clicking an incomplete item triggers a check on the `job_id` to resume/check status.
        *   **Empty State**: Clearly mention if no local history is available.

## Implementation Steps

### Phase 1: Editor/App Logic (`editor.js`, `app.js`)
1.  **Refactor Generation**: Break the `generateLesson` monolithic function.
    *   `startGeneration(request)` -> returns `jobId`.
    *   `pollForFirstSection(jobId)` -> returns partial JSON when ready.
    *   `handoffToViewer(jobId, partialJson)` -> saves state to `localStorage` and redirects.
    *   (New) Implement **History Button** in Index Switch Popup.

### Phase 2: Core Streaming Logic
2.  **Streaming Manager**:
    *   Create `assets/streaming-manager.js`.
    *   Implement `pollJobStatus()`, `handleJobUpdate()`.
    *   Implement `validateAndRepair(json)` pipeline.
    *   Manage `localStorage` updates.

### Phase 3: Viewer UI Updates
3.  **ToC Replacement**:
    *   Remove ToC code from `viewer.js` and `app.js` (or disable).
    *   Implement **History/Lessons Popup**.
    *   Add **New Content Toast** (solid, premium style).
4.  **Section Timer**:
    *   Implement "Ghost" section rows with **Spinner Icons**.
    *   Add **Cancel Button** and API integration.
    *   Clean up status labels.

### Phase 4: API & Data Integration
4.  **Schema Alignment**:
    *   Verify `JobStatusResponse` structure for `result.lesson_json`.
    *   Ensure `progressive-json.js` manages unique IDs or keys to prevent duplication.

## Data Structures

**Local Storage (History)**:
```json
"dle_lessons": {
  "job-123": {
    "id": "job-123",
    "topic": "Python Basics",
    "status": "streaming" | "complete" | "canceled",
    "total_sections": 5,
    "timestamp": 1736848200000,
"lesson_json": { ... }
  }
}
```

**Section Timer State**:
```javascript
section = {
  status: 'active' | 'complete' | 'skipped' | 'generating' | 'pending_queue',
  title: '...',
  // ...
}
```

## Questions / Assumptions
1.  **API Metadata**: We assume `JobStatusResponse` or the first `result` contains `total_steps` or a specific field indicating the number of sections. The user stats: "The jobs api will share how many sections are expected... provided in the first response". We will look for this field (e.g., `expected_sections` or derive from `total_steps` if 1 step = 1 section).
2.  **Titles**: If titles aren't known ahead of time, we will use "Section N".

---

# Task Checklist: Partial Lesson & Streaming Support

- [ ] **Phase 1: Architecture & Specs**
    - [x] Research existing generation and viewer flow
    - [x] Update Specs with User Feedback (Cancel button, History, StreamingManager) <!-- id: 1 -->
    - [ ] Create `StreamingManager` class design

- [ ] **Phase 2: Core Logic (StreamingManager)**
    - [ ] Create `assets/streaming-manager.js`
    - [ ] Implement polling logic with `job_id`
    - [ ] Implement `appendJSON` integration with validation & auto-repair
    - [ ] Implement `localStorage` persistence

- [ ] **Phase 3: Editor Updates**
    - [ ] Refactor `generateLesson` to handle "Handoff"
    - [ ] Implement 3rd "History" button in Index Switch Popup
    - [ ] Save initial job state to `localStorage`

- [ ] **Phase 4: Viewer Updates**
    - [ ] **Remove** Table of Contents completely
    - [ ] Set default visibility to `card`
    - [ ] Implement "History" button in Viewer Header
    - [ ] Integrate `StreamingManager` initialization
    - [ ] Implement "New Content" Toast (No transparency)

- [ ] **Phase 5: Section Timer & Status Panel**
    - [ ] Update UI to list expected sections with "Ghost" rows
    - [ ] Add "Spinning Wheel" for generating sections
    - [ ] Add "Cancel" button with API integration
    - [ ] Remove "Available" text tag (use existing style)

- [ ] **Phase 6: Verification**
    - [ ] Verify partial rendering flow
    - [ ] Verify "Cancel" flow
    - [ ] Verify "History" persistence and resumption
