import logging
from typing import Any

from app.ai.orchestrator import OrchestrationError
from app.config import Settings
from app.core.json import DecimalJSONResponse
from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError


def _coerce_json_safe(value: Any) -> Any:
  """Convert unsupported values into JSON-safe primitives for error responses."""
  # Keep native JSON primitives unchanged.
  if value is None or isinstance(value, bool | int | float | str):
    return value
  # Recursively sanitize mapping values so nested contexts remain serializable.
  if isinstance(value, dict):
    return {str(key): _coerce_json_safe(item) for key, item in value.items()}
  # Normalize iterable containers to lists for deterministic JSON encoding.
  if isinstance(value, list | tuple | set):
    return [_coerce_json_safe(item) for item in value]
  # Serialize exception instances explicitly to avoid leaking non-serializable objects.
  if isinstance(value, BaseException):
    error_message = str(value)
    if error_message:
      return f"{type(value).__name__}: {error_message}"
    return type(value).__name__
  # Fallback to string coercion for arbitrary custom objects.
  return str(value)


def _error_payload(detail: Any, settings: Settings, *, request_id: str | None = None) -> dict[str, Any]:
  """Build a safe error payload that avoids leaking internal details to clients."""
  payload: dict[str, Any] = {"detail": detail}
  # Attach a request id so support can correlate client reports to server logs.
  if request_id:
    payload["requestId"] = request_id
  return payload


def _sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
  """Return validation errors without raw input payloads."""
  sanitized: list[dict[str, Any]] = []
  # Strip payload values so logs are useful without leaking request bodies.
  for error in errors:
    scrubbed = {key: value for key, value in error.items() if key != "input"}
    # Remove nested input values from context payloads as well.
    if "ctx" in scrubbed and isinstance(scrubbed["ctx"], dict):
      scrubbed_ctx = dict(scrubbed["ctx"])
      scrubbed_ctx.pop("input", None)
      scrubbed["ctx"] = scrubbed_ctx

    sanitized.append(_coerce_json_safe(scrubbed))

  return sanitized


def _sanitize_http_detail(detail: Any) -> Any:
  """Return an HTTPException detail payload safe for logs."""
  # Redact common payload keys while keeping structure for debugging.
  if isinstance(detail, dict):
    redacted: dict[str, Any] = {}
    # Walk keys so nested payloads get scrubbed consistently.
    for key, value in detail.items():
      if key in {"input", "body", "payload", "content"}:
        continue
      redacted[key] = _sanitize_http_detail(value)
    return redacted

  # Normalize lists of detail entries.
  if isinstance(detail, list):
    return [_sanitize_http_detail(item) for item in detail]

  return detail


async def global_exception_handler(request: Request, exc: Exception) -> DecimalJSONResponse:
  """Global exception handler to catch unhandled errors."""
  from app.config import get_settings

  settings = get_settings()
  logger = logging.getLogger("uvicorn.error")
  request_id = getattr(request.state, "request_id", None)
  logger.error("Global exception request_id=%s path=%s error_type=%s", request_id, request.url.path, type(exc).__name__, exc_info=True)
  return DecimalJSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=_error_payload("Internal Server Error", settings, request_id=request_id))


async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> DecimalJSONResponse:
  """Log request validation errors for debugging without leaking payloads."""
  from app.config import get_settings

  settings = get_settings()
  request_id = getattr(request.state, "request_id", None)
  sanitized_errors = _sanitize_validation_errors(exc.errors())
  # Keep validation logs concise because 422s are client-correctable and expected.
  logger = logging.getLogger("uvicorn.error")
  logger.warning("Request validation failed request_id=%s path=%s method=%s errors=%s", request_id, request.url.path, request.method, sanitized_errors)
  return DecimalJSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=_error_payload(sanitized_errors, settings, request_id=request_id))


async def http_exception_handler(request: Request, exc: HTTPException) -> DecimalJSONResponse:
  """Handle FastAPI HTTPExceptions while avoiding leaking internal diagnostics."""
  from app.config import get_settings

  settings = get_settings()
  request_id = getattr(request.state, "request_id", None)
  # Log 5xx HTTPExceptions with a traceback for diagnostics; do not expose `exc.detail` to callers.
  if exc.status_code >= 500:
    logger = logging.getLogger("uvicorn.error")
    logger.error("HTTPException request_id=%s path=%s status_code=%s detail=%s", request_id, request.url.path, exc.status_code, exc.detail, exc_info=True)
    return DecimalJSONResponse(status_code=exc.status_code, content=_error_payload("Internal Server Error", settings, request_id=request_id))

  # Log 4xx HTTPExceptions when explicitly enabled for debugging.
  if settings.log_http_4xx:
    logger = logging.getLogger("uvicorn.error")
    sanitized_detail = _sanitize_http_detail(exc.detail)
    logger.warning("HTTPException request_id=%s path=%s status_code=%s detail=%s", request_id, request.url.path, exc.status_code, sanitized_detail, exc_info=True)

  # Preserve 4xx details for client-correctable errors.
  return DecimalJSONResponse(status_code=exc.status_code, content=_error_payload(exc.detail, settings, request_id=request_id))


async def orchestration_exception_handler(request: Request, exc: OrchestrationError) -> DecimalJSONResponse:
  """Return a structured failure response for orchestration errors."""
  from app.config import get_settings

  settings = get_settings()
  # Log orchestration failures with stack traces for diagnostics.
  logger = logging.getLogger("uvicorn.error")
  request_id = getattr(request.state, "request_id", None)
  logger.error("Orchestration failure request_id=%s path=%s error_type=%s", request_id, request.url.path, type(exc).__name__, exc_info=True)
  # Avoid returning orchestration logs to callers; they may contain prompts, tool output, or PII.
  return DecimalJSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=_error_payload("Internal Server Error", settings, request_id=request_id))
