# Research Agent Code Review Defects

This document summarizes the code defects raised by Gemini Code Assist in the recent pull request for the Research Agent implementation.

## Extracted Defects

### 1. Broad Exception Handling in Crawling Phase
- **Location**: `dgs-backend/app/api/routes/research.py` (Lines 121-124)
- **Description**: An `except Exception as e: pass` block is used during the crawling phase. This is too broad and can hide critical issues like `AsyncWebCrawler` initialization failures.
- **Suggested Fix**: Catch more specific exceptions and log them at an error level before proceeding.

### 2. Privacy Concern: Logging `user_id` to Public Collection
- **Location**: `dgs-backend/app/api/routes/research.py` (Line 200)
- **Description**: The `user_id` is logged to the `public` research logs collection. If this collection is truly public, this is a privacy concern.
- **Suggested Fix**: Anonymize or omit `user_id` from public collections.

### 3. Direct use of `os.getenv` for `GEMINI_API_KEY`
- **Location**: `dgs-backend/app/api/routes/research.py` (Line 25)
- **Description**: `GEMINI_API_KEY` is retrieved directly from environment variables.
- **Suggested Fix**: Use the centralized `settings` object for consistency with other clients (e.g., Tavily).

### 4. Hardcoded Model Name for Query Classification
- **Location**: `dgs-backend/app/api/routes/research.py` (Line 44)
- **Description**: The model name `gemini-2.5-flash` is hardcoded.
- **Suggested Fix**: Make the model name configurable via environment variables and the `Settings` object.

### 5. Fragile Query Classification Fallback Logic
- **Location**: `dgs-backend/app/api/routes/research.py` (Lines 47-50)
- **Description**: The fallback logic uses simple string containment (e.g., `if cat.lower() in category.lower()`), which might match incorrectly if the model returns a full sentence.
- **Suggested Fix**: Use regex or refine the prompt to ensure the model returns only the category name.

### 6. Hardcoded `max_results` for Tavily Search
- **Location**: `dgs-backend/app/api/routes/research.py` (Line 76)
- **Description**: `max_results` is hardcoded to 5.
- **Suggested Fix**: Make this value configurable through application settings.

### 7. User-unfriendly Fallback Title for Crawled Data
- **Location**: `dgs-backend/app/api/routes/research.py` (Line 118)
- **Description**: Using the URL as a fallback title when `result.title` might be available.
- **Suggested Fix**: Extract the actual page title from `result.title` or `result.metadata` if available.

### 8. Typo/Incomplete Citation Implementation
- **Location**: `dgs-backend/app/api/routes/research.py` (Line 144)
- **Description**: The citation placeholder `[{1}]` looks like a typo or an incomplete dynamic implementation.
- **Suggested Fix**: Clarify if it's a static example or handle dynamic insertion in the prompt construction.

### 9. Hardcoded Model Name for Answer Synthesis
- **Location**: `dgs-backend/app/api/routes/research.py` (Line 156)
- **Description**: The model name `gemini-1.5-pro` is hardcoded.
- **Suggested Fix**: Make the synthesis model name configurable via settings.

### 10. Hardcoded `app_id`
- **Location**: `dgs-backend/app/api/routes/research.py` (Line 183)
- **Description**: `app_id` is hardcoded to "dgs".
- **Suggested Fix**: Retrieve `app_id` from the application settings (`settings.app_id`) for consistency across environments.

---

## Remediation Checklist

- [x] Refactor broad `except` block in crawling phase (Lines 121-124).
- [x] Review and fix `user_id` logging for privacy (Line 200).
- [x] Move `GEMINI_API_KEY` retrieval to `settings` (Line 25).
- [x] Make Query Classification model configurable (Line 44).
- [x] Improve Query Classification fallback logic (Lines 47-50).
- [x] Make Tavily `max_results` configurable (Line 76).
- [x] Improve crawled data title extraction (Line 118).
- [x] Fix citation placeholder typo/logic in synthesis prompt (Line 144).
- [x] Make Synthesis model configurable (Line 156).
- [x] Make `app_id` configurable via settings (Line 183).
