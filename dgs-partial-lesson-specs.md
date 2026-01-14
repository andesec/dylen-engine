# DGS Backend Specs: Partial Lesson Streaming

## Overview
This document outlines the backend changes required in the Digital Generation Service (DGS) to support the "Partial Lesson" (Streaming) feature in the frontend DLE. The goal is to allow the frontend to retrieve and display lesson sections as soon as they are generated, rather than waiting for the entire job to complete.

Reference: `partial-lesson-specs.md` (Frontend Specs)

## API Requirements

### 1. Job Creation (`POST /v1/jobs`)
*   **Requirement**: The response (or the initial status response) must provide the total number of expected steps/sections.
*   **Current State**: `JobStatusResponse` already has `total_steps`.
*   **Change**: Ensure `total_steps` is calculated and persisted immediately upon job creation or at the very start of processing, so the first polling request (or the creation response if possible) returns it.

### 2. Job Polling (`GET /v1/jobs/{job_id}`)
*   **Requirement**: The endpoints must return partial results in the `result` field while the job status is still `running`.
*   **Current State**: `result` is typically populated only when status is `done`.
*   **Change**:
    *   Update the specific job processor to persist the accumulated `lesson_json` to the database incrementally.
    *   Ensure the `result` field in the API response reflects this current partial state.
    *   The frontend will handle "merging", so returning the *full current accumulated JSON* is acceptable (and simpler than implementing a diff/patch mechanism).

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
    *   Update `_progress_callback` to accept `partial_json` from the orchestrator.
    *   Pass this `partial_json` to the `JobProgressTracker`.

### 3. Progress Tracker (`app/jobs/progress.py`)
*   **Current**: `_update_job` persists status, phase, logs, etc.
*   **Change**:
    *   Update `JobProgressTracker.complete_step` (and internal `_update_job`) to accept an optional `result_json` argument.
    *   Persist this `result_json` to the `JobsRepository`.

### 4. Job Repository (`app/storage/*_jobs_repo.py`)
*   **Current**: `update_job` updates the job record.
*   **Change**: Ensure `update_job` handles the `result_json` update correctly for both Postgres and DynamoDB implementations.

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

**JobStatusResponse Result (Partial)**
The `result` field in `JobStatusResponse` will be a valid (but potentially incomplete) `LessonModel` JSON.
```json
{
  "job_id": "...",
  "status": "running",
  "total_steps": 10,
  "completed_steps": 2,
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
    // Remaining modules/sections might be missing or empty
  }
}
```
