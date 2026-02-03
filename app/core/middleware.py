import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("app.core.middleware")


def _redact_sensitive_keys(data: Any) -> Any:
  """Redact sensitive keys from a dictionary or list recursively."""
  if isinstance(data, dict):
    return {k: ("***" if k.lower() in ("password", "token", "key", "authorization", "cookie", "secret") else _redact_sensitive_keys(v)) for k, v in data.items()}
  if isinstance(data, list):
    return [_redact_sensitive_keys(item) for item in data]
  return data


def _normalize_headers(scope: Scope) -> dict[str, str]:
  """Normalize scope headers so downstream logging can check content type safely."""
  # Convert byte headers into a case-insensitive mapping for logging decisions.
  header_map = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
  return header_map


def _build_request_url(scope: Scope) -> str:
  """Build a readable URL path for logging without relying on Request bodies."""
  # Construct a path with query string to mirror incoming request targets.
  path = scope.get("path", "")
  query_string = scope.get("query_string", b"")
  if query_string:
    return f"{path}?{query_string.decode('latin-1')}"

  return path


class RequestLoggingMiddleware:
  """Log request/response details while preserving body streams for downstream handlers."""

  def __init__(self, app: ASGIApp) -> None:
    """Store the downstream ASGI application for request logging."""
    self.app = app

  async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
    """Record request/response metadata and replay bodies to avoid side effects."""
    # Skip non-HTTP scopes to avoid interfering with websocket or lifespan events.
    if scope["type"] != "http":
      await self.app(scope, receive, send)
      return

    # Start timing early so latency includes downstream handlers.
    start_time = time.time()
    # Log the incoming request metadata for traceability.
    method = scope.get("method", "UNKNOWN")
    url = _build_request_url(scope)
    logger.info(f"Incoming request: {method} {url}")

    # Capture body messages so downstream handlers can replay them safely.
    body = b""
    messages: list[dict[str, Any]] = []
    more_body = True
    try:
      # Drain the incoming receive channel to capture the request body.
      while more_body:
        message = await receive()
        messages.append(message)
        body += message.get("body", b"")
        more_body = message.get("more_body", False)

      # Log payloads only for JSON requests to avoid noisy or binary logs.
      headers = _normalize_headers(scope)
      content_type = headers.get("content-type", "")
      if content_type.startswith("application/json") and body:
        try:
          payload = json.loads(body)
          safe_payload = _redact_sensitive_keys(payload)
          logger.debug(f"Request Body: {json.dumps(safe_payload)}")
        except json.JSONDecodeError:
          # Fallback if valid JSON but not parseable (or strict parsing fails)
          logger.debug(f"Request Body (raw): {body.decode('utf-8')}")

    except Exception as exc:
      # Log body parsing errors so observability does not hide logging issues.
      logger.warning(f"Failed to log request body: {exc}")

    # Replay stored messages so downstream consumers can read the body.
    message_queue = list(messages)

    async def receive_replay() -> dict[str, Any]:
      # Feed stored request body chunks back to the downstream application.
      if message_queue:
        return message_queue.pop(0)

      return {"type": "http.request", "body": b"", "more_body": False}

    # Capture response status for response timing logs.
    status_code: int | None = None

    async def send_wrapper(message: dict[str, Any]) -> None:
      # Track the response status from the response start message.
      nonlocal status_code
      if message.get("type") == "http.response.start":
        status_code = message.get("status")

      await send(message)

    # Execute downstream handlers to keep middleware focused on observation.
    await self.app(scope, receive_replay, send_wrapper)

    # Emit response timing metrics for operational visibility.
    process_time = (time.time() - start_time) * 1000
    response_status = status_code or 0
    logger.info(f"Response: {response_status} (took {process_time:.2f}ms)")


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


class SecurityHeadersMiddleware:
  """Middleware to strip sensitive headers from responses."""

  def __init__(self, app: ASGIApp) -> None:
    """Store the downstream ASGI application."""
    self.app = app

  async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
    """Intercept response headers to remove sensitive information."""
    if scope["type"] != "http":
      await self.app(scope, receive, send)
      return

    async def send_wrapper(message: dict[str, Any]) -> None:
      if message["type"] == "http.response.start":
        headers = MutableHeaders(scope=message)
        # Strip X-Powered-By if present
        if "x-powered-by" in headers:
          del headers["x-powered-by"]
        # Strip Server if present (though Uvicorn adds it later, this handles app-level additions)
        if "server" in headers:
          del headers["server"]

      await send(message)

    await self.app(scope, receive, send_wrapper)
