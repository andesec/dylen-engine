# Refactoring Plan for DGS `main.py`

This document outlines the sequence of changes to split `main.py` into modular components without altering behavior.

## Sequence of Operations

1.  **Create Directory Structure**
    *   Ensure the following directories exist:
        *   `app/core`
        *   `app/api/routes`
        *   `app/services`
        *   `app/storage` (already exists, verify)

2.  **Extract Shared Utilities (`app/services/widgets.py`)**
    *   **Goal**: Isolate dependency-free helpers used by models.
    *   **Content**: `_widget_id_map`, `_normalize_widget_ids`, `_normalize_option_id`.

3.  **Extract API Models (`app/api/models.py`)**
    *   **Goal**: Centralize Pydantic models to avoid circular imports.
    *   **Content**: `GenerateLessonRequest`, `JobStatusResponse`, `KnowledgeModel`, etc.
    *   **Dependencies**: `app/services/widgets.py` (for normalization validators).

4.  **Extract Core Modules**
    *   **`app/core/json.py`**: `DecimalJSONEncoder`, `DecimalJSONResponse`.
    *   **`app/core/logging.py`**: Logging setup (`setup_logging`, `TruncatedFormatter`, `_log_widget_registry`, `_build_handlers`).
    *   **`app/core/middleware.py`**: `log_requests` middleware.
    *   **`app/core/exceptions.py`**: `global_exception_handler`, `orchestration_exception_handler`, `_error_payload`.

5.  **Extract Dependencies and Services**
    *   **`app/api/deps.py`**: `_require_dev_key`.
    *   **`app/services/model_routing.py`**: `_resolve_model_selection` and provider logic.
    *   **`app/services/orchestrator.py`**: `_get_orchestrator` factory.
    *   **`app/storage/factory.py`**: `_get_repo`, `_get_jobs_repo`.
    *   **`app/services/validation.py`**: `_validate_generate_request`, `MAX_REQUEST_BYTES`, validation helpers.
    *   **`app/services/jobs.py`**: Job processing logic (`_create_job_record`, `_process_job_async`, `_kickoff_job_processing`, `_job_status_from_record`).

6.  **Extract Lifespan and Worker (`app/core/lifespan.py`)**
    *   **Goal**: Manage app lifecycle and background worker.
    *   **Content**: `lifespan`, `_start_job_worker`, `_job_worker_loop`.
    *   **Dependencies**: `app/services/jobs.py` (for `_log_job_task_failure` and `JobProcessor`).

7.  **Extract Routes**
    *   **`app/api/routes/health.py`**: `/health`.
    *   **`app/api/routes/writing.py`**: `/v1/writing/check`.
    *   **`app/api/routes/lessons.py`**: Lesson endpoints (`catalog`, `validate`, `generate`, `get_lesson`).
    *   **`app/api/routes/jobs.py`**: Job endpoints (`create`, `status`, `cancel`, `retry`).

8.  **Refactor `app/main.py`**
    *   **Goal**: Reassemble the application.
    *   **Content**: `FastAPI` init, middleware add, exception handler registration, router inclusion.

9.  **Verification**
    *   Run smoke tests to ensure API behavior remains identical.
