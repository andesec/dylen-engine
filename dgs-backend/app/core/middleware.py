import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

logger = logging.getLogger("app.core.middleware")


async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
  """Log request/response metadata to support tracing without exposing sensitive payloads."""
  # Track start time to compute request duration without storing payloads.
  start_time = time.time()
  # Log request metadata to aid tracing while avoiding sensitive payloads.
  logger.info(f"Incoming request: {request.method} {request.url}")
  # Only log request sizing hints from headers to avoid credential exposure.
  content_type = request.headers.get("content-type")
  content_length = request.headers.get("content-length")
  if content_type or content_length:
    logger.debug(f"Request metadata: content-type={content_type} content-length={content_length}")

  # Delegate to downstream handlers while keeping middleware lightweight.
  response = await call_next(request)

  # Calculate elapsed time for response logging.
  process_time = (time.time() - start_time) * 1000
  # Log response status and timing for observability.
  logger.info(f"Response: {response.status_code} (took {process_time:.2f}ms)")
  return response
