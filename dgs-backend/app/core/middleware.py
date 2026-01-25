import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

logger = logging.getLogger("app.core.middleware")


async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
  """Capture request/response details to aid debugging without changing behavior."""
  # Start timing early so latency includes downstream handlers.
  start_time = time.time()
  # Log the incoming request metadata for traceability.
  logger.info(f"Incoming request: {request.method} {request.url}")

  try:
    # Only attempt JSON body logging to avoid consuming streaming bodies.
    if request.headers.get("content-type") == "application/json":
      body = await request.body()
      if body:
        # Log payloads at debug level to avoid noisy production logs.
        logger.debug(f"Request Body: {body.decode('utf-8')}")

  except Exception as e:
    # Swallow logging errors so middleware never blocks a request.
    logger.warning(f"Failed to log request body: {e}")

  # Execute downstream handlers to keep middleware focused on observation.
  response = await call_next(request)

  # Emit response timing metrics for operational visibility.
  process_time = (time.time() - start_time) * 1000
  logger.info(f"Response: {response.status_code} (took {process_time:.2f}ms)")
  return response
