"""Global exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, status

from app.ai.orchestrator import OrchestrationError
from app.config import get_settings
from app.core.json import DecimalJSONResponse

settings = get_settings()


def _error_payload(detail: str, *, error: str | None = None, logs: list[str] | None = None) -> dict[str, Any]:
  """Build error payloads with optional debug detail."""
  payload = {"detail": detail}

  # Only attach diagnostic details when debug mode is enabled.
  if settings.debug:
    if error is not None:
      payload["error"] = error

    if logs is not None:
      payload["logs"] = logs

  return payload


async def global_exception_handler(request: Request, exc: Exception) -> DecimalJSONResponse:
  """Global exception handler to catch unhandled errors."""
  logger = logging.getLogger("uvicorn.error")
  logger.error(f"Global exception: {exc}", exc_info=True)
  return DecimalJSONResponse(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=_error_payload("Internal Server Error", error=str(exc))
  )


async def orchestration_exception_handler(request: Request, exc: OrchestrationError) -> DecimalJSONResponse:
  """Return a structured failure response for orchestration errors."""
  # Log orchestration failures with stack traces for diagnostics.
  logger = logging.getLogger("uvicorn.error")
  logger.error("Orchestration failure: %s", exc, exc_info=True)
  # Provide the failure logs so callers can close out the request with context.
  return DecimalJSONResponse(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    content=_error_payload("Orchestration failed", error=str(exc), logs=exc.logs),
  )
