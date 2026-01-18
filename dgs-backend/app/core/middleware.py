"""Middleware components."""

from __future__ import annotations

import time
import logging
from collections.abc import Awaitable, Callable
from fastapi import Request, Response

logger = logging.getLogger("app.core.middleware")


async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
  """Log all incoming requests and outgoing responses."""
  start_time = time.time()
  logger.info(f"Incoming request: {request.method} {request.url}")

  try:
    if request.headers.get("content-type") == "application/json":
      body = await request.body()
      if body:
        logger.debug(f"Request Body: {body.decode('utf-8')}")
  except Exception:
    pass  # Don't fail if body logging fails

  response = await call_next(request)

  process_time = (time.time() - start_time) * 1000
  logger.info(f"Response: {response.status_code} (took {process_time:.2f}ms)")
  return response
