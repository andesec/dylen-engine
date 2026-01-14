# DGS Backend Specs: Partial Lesson Streaming

## Overview
This document outlines the backend changes required in the Digital Generation Service (DGS) to support the "Partial Lesson" (Streaming) feature in the frontend DLE. The goal is to allow the frontend to retrieve and display lesson sections as soon as they are generated, rather than waiting for the entire job to complete.

Reference: `partial-lesson-specs.md` (Frontend Specs)

## API Requirements

### 1. Job Creation (`POST /v1/jobs`)
*   **Requirement**: The response must immediately provide the total number of expected sections (`total_sections`) along with the `job_id`. This allows the frontend to initialize the "ghost" section list immediately.
*   **Current State**: `JobCreateResponse` only contains `job_id`.
*   **Change**:
    *   Update `JobCreateResponse` schema to include `expected_sections` (int).
    *   Logic: In `_create_job_record` (or `build_call_plan` which is called there), calculate the number of sections based on the requested `depth` *before* the job is queued.
    *   Return `{ "job_id": "...", "expected_sections": 5 }`.

### 2. Job Polling (`GET /v1/jobs/{job_id}`)
*   **Requirement**:
    *   The `result` field must return partial lesson JSON while running.
    *   It must also explicitly identify *which* section is currently being generated.
    *   It must indicate if a specific section generation has failed and is being retried.
*   **Current State**: `JobStatusResponse` has generic `status`, `phase`, `subphase`.
*   **Change**:
    *   Augment `JobStatusResponse` (or the `metadata` within `result`) to include:
        *   `current_section_index`: 0-based index of the section currently under construction.
        *   `section_status`: e.g., "generating", "retrying", "completed".
        *   `retry_count`: If retrying, how many attempts so far.
    *   **Persistence Source**: The API endpoint **must** retrieve this data from the `jobs` table in the database. The Worker saves to the DB; the API reads from the DB. It should *not* rely on in-memory state.
    *   **Final State**: When the job is `done`, the final complete JSON is moved/copied to the `lessons` table, but the `jobs` table record remains the source for the generation history/logs.

### 3. Job Cancellation (`POST /v1/jobs/{job_id}/cancel`)
*   **Requirement**: Allow users to stop generation.
*   **Current State**: Endpoint exists and sets status to `canceled`.
*   **Change**: Verify and ensure that the background worker checks this status effectively and halts processing immediately to save costs/resources.

## Internal Architecture Updates

### 1. Orchestrator (`app/ai/orchestrator.py`)
*   **Current**: `generate_lesson` runs sequentially and returns a final `OrchestrationResult`.
*   **Change**: 
    *   Modify `generate_lesson` to support a `yield` or callback mechanism that exposes the `current_lesson_state` after each structural step (e.g., after each Structurer call).
    *   The `progress_callback` signature needs to be expanded or a new callback added to accept `partial_json`.

### 2. Job Worker (`app/jobs/worker.py`)
*   **Current**: `_progress_callback` updates the `JobProgressTracker` with phase/logs but not data.
*   **Change**:
    *   Update `_progress_callback` to accept `partial_json` and `section_metadata` (index, retry status) from the orchestrator.
    *   Pass this data to the `JobProgressTracker`.
    *   **Crucial**: The Worker must write this data to the `jobs` repository (DB) immediately upon callback.

### 3. Progress Tracker (`app/jobs/progress.py`)
*   **Current**: `_update_job` persists status, phase, logs, etc.
*   **Change**:
    *   Update `JobProgressTracker.complete_step` (and internal `_update_job`) to accept `result_json` and `current_section_info`.
    *   Persist this to the `JobsRepository` so the API can read it.

### 4. Job Repository (`app/storage/*_jobs_repo.py`)
*   **Current**: `update_job` updates the job record.
*   **Change**: Ensure `update_job` handles the `result_json` update correctly.

### 5. Final Persistence (`app/main.py`)
*   **Clarification**: Ensure that upon successful completion (`status='done'`), the final full `lesson_json` is explicitly saved to the `lessons` table (as is currently done), while the `jobs` table retains the record of the run.

## Implementation Plan

### Phase 1: Core Orchestration Streaming
1.  **Code**: Modify `DgsOrchestrator.generate_lesson` to construct the `lesson_json` incrementally.
2.  **Code**: In the loop where sections are generated (e.g., `Structurer`), invoke the callback with the updated `lesson_json`.

### Phase 2: Worker & Tracker Integration
3.  **Code**: Update `JobProgressTracker` methods (`complete_step`, `set_phase`, etc.) to accept `partial_result`.
4.  **Code**: Update `JobProgressTracker._update_job` to include `result_json` in the payload passed to the repo.
5.  **Code**: Update `JobProcessor._process_lesson_generation` -> `_progress_callback` to receive the data from Orchestrator and pass it to Tracker.

### Phase 3: Verification
6.  **Test**: Unit test `JobProgressTracker` to ensure it saves partial results.
7.  **Test**: Integration test `POST /v1/jobs` -> `GET /v1/jobs/{id}` loop to verify `result` grows over time.
8.  **Test**: Verify `cancel` endpoint stops the worker loop effectively.

## Data Structures

**JobCreateResponse**
```json
{
  "job_id": "job-123",
  "expected_sections": 5
}
```

**JobStatusResponse Result (Partial)**
The `result` field in `JobStatusResponse` will be a valid (but potentially incomplete) `LessonModel` JSON.
The top-level `phase` or `subphase` (or a new `meta` field in the response) will track section details.

```json
{
  "job_id": "...",
  "status": "running",
  "expected_sections": 10,
  "completed_sections": 2,
  "current_section": {
     "index": 3,
     "title": "Control Flow",
     "status": "retrying",
     "retry_count": 1
  },
  "result": {
    "title": "Python Basics",
    "modules": [
      {
        "title": "Module 1",
        "sections": [
          { "title": "Section 1", "content": [...] }
        ]
      }
    ]
  }
}
```
