# Code Quality Report

This report identifies potential dead code, errors, failures, edge cases, and SOLID violations in the codebase.

## 1. Dead Code and Unreachable Logic

### `app/ai/orchestrator.py` (`DylenOrchestrator`)
- **`_convert_to_shorthand`**: Contains a try-except block that swallows exceptions and returns original JSON. The usage of `msgspec.convert` with `app.schema.widget_models.Section` implies a strict schema, but fallback logic suggests it might be flaky.
- **`_depth_profile`**: Hardcoded mapping. Raises `ValueError` for unknown inputs, which can crash the application if input validation is bypassed or changed.

### `app/jobs/worker.py` (`JobProcessor`)
- **`_ALLOWED_RETRY_AGENTS`**: Contains "gatherer" and "structurer" which do not correspond to any known agents in `app/ai/agents`.
- **`_to_section_numbers`**: Trivial helper function that could be inlined.
- **Redundant Section Persistence**: The `_process_lesson_generation` method attempts to save all sections at the end of the job, duplicating the work done by `DylenOrchestrator` which saves sections incrementally. This leads to duplicate section records in the database.
- **`_strip_internal_request_fields`**: Duplicated logic or could be centralized.
- **Commented Out Code**: Multiple instances of commented out code (e.g., `# lesson_json used to be here`, `# extracted_plan removed (unused)`).

### `app/ai/agents/coach.py` (`CoachAgent`)
- **Unused Variable**: `logger` is redefined inside `run`, shadowing the module-level logger.

## 2. Potential Errors, Failures, and Edge Cases

### `app/jobs/worker.py` (`JobProcessor`)
- **Duplicate Section Records**: As noted above, `JobProcessor` saves all sections *after* orchestration, while `DylenOrchestrator` saves them *during* orchestration. Since `uuid.uuid4()` is used for `section_id` in both places, this results in duplicate section entries for the same lesson.
- **Timeout Logic**: The timeout logic in `_process_lesson_generation` is complex, manually checking `time.monotonic()` in multiple places. It could be simplified or moved to a decorator/context manager.
- **Quota Logic**: Relies on `runtime_config` returning valid integers. If configuration is missing or malformed, it raises `ValueError`.

### `app/ai/agents/coach.py` (`CoachAgent`)
- **Silent Failures in TTS**: The `run` method catches `NotImplementedError` and `Exception` during `generate_speech` and logs a warning, but continues execution. This means a lesson section could have missing audio segments without failing the job, which might be undesirable behavior (silent data loss).
- **Transaction Management**: The `run` method performs multiple database operations (reservation check, reservation commit, audio persistence) mixed with long-running LLM calls. This holds database connections longer than necessary and risks timeouts.

### `app/ai/agents/research.py` (`ResearchAgent`)
- **Blocking DNS Resolution**: `_validate_url_sync` uses `socket.gethostbyname` which is blocking. Although wrapped in `run_in_threadpool`, it can still exhaust the thread pool under load.
- **Empty Crawl Results**: `synthesize` raises `RuntimeError` if *no* sources are crawled, but `_crawl_urls` might return an empty list silently if individual URLs fail.

## 3. SOLID Violations and Complexity

### `app/ai/orchestrator.py` (`DylenOrchestrator`) - **God Class**
- **SRP Violation**: This class handles:
    -   Orchestration logic (planning, section generation, repair).
    -   Database persistence (saving sections, updating lesson plans).
    -   Quota management (checking and enforcing limits).
    -   Job creation (spawning child jobs for widgets).
- **Complexity**: `_run_section_generation_phase` and `_generate_section` are highly coupled and contain mixed levels of abstraction.

### `app/jobs/worker.py` (`JobProcessor`) - **OCP Violation**
- **Open/Closed Principle**: The `process_job` method uses a switch-case statement on `job.target_agent`. Adding a new agent type requires modifying this class, violating OCP.
- **Coupling**: It is tightly coupled to `DylenOrchestrator`, `CoachAgent`, `FensterBuilderAgent`, and specific database repositories.

### `app/ai/agents/coach.py` (`CoachAgent`) - **SRP Violation**
- **Single Responsibility Principle**: The agent is responsible for:
    -   Core logic (LLM generation).
    -   Quota management (check, reserve, commit, release).
    -   Database persistence (saving audio records).
    -   TTS generation.
- **Duplication**: The quota management logic is duplicated in `FensterBuilderAgent`.

### `app/ai/agents/research.py` (`ResearchAgent`) - **DI Violation**
- **Dependency Injection**: It instantiates `GeminiProvider` and `TavilyProvider` directly in `__init__`, making it difficult to mock or swap providers for testing.
