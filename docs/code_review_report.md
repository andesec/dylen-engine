# Code Review Report

## Executive Summary

This report details the findings of a comprehensive code review of the `dylen-engine` application (`app/` directory). The review focuses on adherence to Object-Oriented Design (OOD) principles, SOLID principles, and modern standards for building AI applications.

**Overall Assessment:**
The codebase exhibits a high level of quality, demonstrating a strong grasp of modern Python asynchronous programming, type safety, and architectural layering. The use of Pydantic for data validation and SQLAlchemy 2.0 for persistence is excellent. However, there are notable opportunities to improve cohesion and reduce coupling in the core orchestration and job processing layers.

## Compliance Summary

| Principle/Standard | Status | Notes |
| :--- | :--- | :--- |
| **SRP (Single Responsibility)** | ⚠️ Mixed | Logic generally well-separated, but `Orchestrator` and `JobProcessor` are "God Classes". |
| **OCP (Open/Closed)** | ❌ Violation | Adding new job types or agents requires modifying core switch statements (`JobProcessor`). |
| **LSP (Liskov Substitution)** | ✅ Pass | Protocols and Base classes (`BaseAgent`, `JobsRepository`) are respected. |
| **ISP (Interface Segregation)** | ⚠️ Mixed | Repositories are slightly broad; agents share a generic `BaseAgent` interface. |
| **DIP (Dependency Inversion)** | ⚠️ Mixed | Dependency injection used in some places (API), but manual instantiation common in Agents/Services. |
| **Async/Await** | ✅ Pass | Consistently applied throughout the application. |
| **Type Hinting** | ✅ Pass | Extensive use of Python type hints and Pydantic. |
| **Security** | ✅ Pass | RBAC, Firebase Auth, and sanitization (Safe Logs) are well implemented. |

## detailed File-by-File Analysis

### 1. `app/ai/orchestrator.py`
*   **Issues:**
    *   **SRP Violation:** `DylenOrchestrator` handles planning, generation, stitching, logging, progress reporting, and *job creation* for downstream tasks (`_create_widget_jobs`). It knows too much about the system.
    *   **DIP Violation:** `_initialize_agents` manually instantiates `PlannerAgent`, `SectionBuilder`, etc. This prevents swapping implementations for testing or extension.
    *   **Hardcoded Config:** `DEFAULT_MODEL` is hardcoded.
*   **Fix:** Inject agent factories or instances into `DylenOrchestrator`. Extract `WidgetJobCreator` strategy.

### 2. `app/jobs/worker.py`
*   **Issues:**
    *   **OCP Violation:** `process_job` uses a switch statement on `job.target_agent`. Adding a new agent requires modifying this class.
    *   **SRP Violation:** `_process_lesson_generation` is a massive method (200+ lines) mixing orchestration, error handling, and repository updates.
    *   **Coupling:** Hard dependency on concrete agent classes (`FensterBuilderAgent`, `CoachAgent`).
*   **Fix:** Use a Strategy pattern (`JobHandler` interface) and a registry to route jobs to handlers.

### 3. `app/services/jobs.py`
*   **Issues:**
    *   **OCP Violation:** `_parse_job_request` modifies code to handle different request models (`GenerateLessonRequest`, `WritingCheckRequest`).
*   **Fix:** Use a polymorphic request model or a registry for request parsers.

### 4. `app/api/routes/admin.py`
*   **Issues:**
    *   **DIP Violation:** Helper functions `get_jobs_repo` manually instantiate `PostgresJobsRepository`. API routes should depend on the `JobsRepository` Protocol, injected via FastAPI dependencies (`Depends`).
*   **Fix:** Create a `get_jobs_repo` dependency in `app/api/deps.py` that returns the configured implementation.

### 5. `app/ai/agents/research.py`
*   **Issues:**
    *   **DIP Violation:** `ResearchAgent` instantiates `GeminiProvider` and `TavilyProvider` directly.
    *   **Coupling:** Writes directly to Firestore using `firebase_admin`. This couples the agent to a specific storage mechanism.
*   **Fix:** Inject providers. Extract `AuditLogger` or `ResearchRepository` interface for storage.

### 6. `app/ai/agents/stitcher.py`
*   **Issues:**
    *   **SRP Violation:** `_output_dle_shorthand` is a massive static method containing logic for converting every widget type to shorthand. This belongs in a separate `WidgetConverter` or `SchemaMapper` class.
*   **Fix:** Extract widget conversion logic to a dedicated utility or service.

### 7. `app/ai/agents/coach.py`
*   **Issues:**
    *   **DIP Violation:** `run()` calls `get_session_factory()` directly to get a DB session. It should accept a repository or session as a dependency.
*   **Fix:** Pass a `LessonsRepository` or `AuditRepository` to the agent's `run` method or constructor.

### 8. `app/api/routes/fenster.py`
*   **Issues:**
    *   **Hardcoded Logic:** `Depends(require_tier(["Plus", "Pro"]))` hardcodes tier names in the route definition.
*   **Fix:** Move tier requirements to configuration or a more flexible permission system.

### 9. `app/api/routes/tasks.py`
*   **Issues:**
    *   **Security:** `TODO: Verify OIDC token` comment indicates a missing security control for Cloud Task invocation.
*   **Fix:** Implement OIDC token verification for the task handler.

### 10. `app/schema/lesson_models.py`
*   **Issues:**
    *   **Complexity:** Validator logic for widgets (e.g., `SwipeCardsWidget`) is complex and embedded in the schema.
    *   **Type Safety:** Frequent use of `list[Any]` weakens validation guarantees, though validators mitigate this.
*   **Fix:** Extract complex validation logic to helper functions. Use discriminated unions where possible instead of `Any`.

## Recommendations

### Short Term (Refactoring)
1.  **Dependency Injection:** Update `DylenOrchestrator` and `ResearchAgent` to accept their dependencies (Agents, Providers) via their constructors.
2.  **Extract Strategy:** Refactor `JobProcessor` to use a `JobHandler` strategy pattern. Create `FensterJobHandler`, `CoachJobHandler`, `LessonJobHandler`.
3.  **Decouple API from Storage:** Update `app/api/routes/admin.py` to use dependency injection for Repositories instead of direct instantiation.

### Long Term (Architectural)
1.  **Agent Registry:** Create a dynamic registry for Agents and Job Handlers to allow adding new capabilities without modifying core files (OCP).
2.  **Storage Abstraction:** Ensure all DB access (including Firestore in Research) goes through a Repository interface to facilitate testing and potential backend swaps.
3.  **Widget Library:** Extract the widget schema and conversion logic (`StitcherAgent`) into a shared library or module to centralize widget definitions.
