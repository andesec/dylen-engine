import logging
from typing import Any

from app.ai.orchestrator import OrchestrationError
from app.config import Settings
from app.core.json import DecimalJSONResponse
from fastapi import HTTPException, Request, status


def _error_payload(detail: Any, settings: Settings, *, request_id: str | None = None) -> dict[str, Any]:
  """Build a safe error payload that avoids leaking internal details to clients."""
  payload: dict[str, Any] = {"detail": detail}
  # Attach a request id so support can correlate client reports to server logs.
  if request_id:
    payload["requestId"] = request_id
  return payload


async def global_exception_handler(request: Request, exc: Exception) -> DecimalJSONResponse:
  """Global exception handler to catch unhandled errors."""
  from app.config import get_settings

  settings = get_settings()
  logger = logging.getLogger("uvicorn.error")
  request_id = getattr(request.state, "request_id", None)
  logger.error("Global exception request_id=%s path=%s error_type=%s", request_id, request.url.path, type(exc).__name__, exc_info=True)
  return DecimalJSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=_error_payload("Internal Server Error", settings, request_id=request_id))


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
