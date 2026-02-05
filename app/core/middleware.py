import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import get_settings
from fastapi import Request, Response
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("app.core.middleware")


def _redact_sensitive_keys(data: Any) -> Any:
  """Redact sensitive keys from a dictionary or list recursively."""
  if isinstance(data, dict):
    # Keep this list conservative; the function is used by logging and tests.
    sensitive_keys = {"password", "token", "key", "authorization", "cookie", "secret", "email", "full_name", "fullname", "name", "phone", "mobile", "address"}
    return {k: ("***" if k.lower() in sensitive_keys else _redact_sensitive_keys(v)) for k, v in data.items()}
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


def _is_textual_content_type(content_type: str | None) -> bool:
  """Decide whether a body is safe to log as text."""
  if not content_type:
    return False

  # Allow JSON and text types while excluding binary payloads.
  normalized = content_type.lower()
  if "application/json" in normalized:
    return True

  if normalized.endswith("+json"):
    return True

  if normalized.startswith("text/"):
    return True

  if "application/x-www-form-urlencoded" in normalized:
    return True

  return False


def _truncate_body(body: bytes, max_bytes: int) -> tuple[bytes, bool]:
  """Clamp body bytes for logging to avoid oversized log entries."""
  # Cap the body size to the configured limit.
  if len(body) <= max_bytes:
    return body, False

  return body[:max_bytes], True


def _decode_body_text(body: bytes) -> str:
  """Decode bytes into text for logging with safe fallbacks."""
  # Prefer UTF-8 for JSON/text payloads and fall back safely.
  try:
    return body.decode("utf-8")
  except UnicodeDecodeError:
    return body.decode("latin-1", errors="replace")


def _format_body_for_log(body: bytes, content_type: str | None, max_bytes: int) -> str:
  """Format a request/response body for logging with redaction."""
  # Represent empty payloads explicitly to avoid ambiguous logs.
  if not body:
    return "<empty>"

  # Skip binary payloads to avoid dumping raw bytes into logs.
  if not _is_textual_content_type(content_type):
    return f"<non-text body {len(body)} bytes>"

  # Avoid parsing truncated JSON to prevent misleading logs.
  trimmed, truncated = _truncate_body(body, max_bytes)
  if truncated:
    text = _decode_body_text(trimmed)
    return f"{text}...(truncated)"

  text = _decode_body_text(trimmed)
  if content_type and ("application/json" in content_type.lower() or content_type.lower().endswith("+json")):
    try:
      parsed = json.loads(text)
    except json.JSONDecodeError:
      return text

    redacted = _redact_sensitive_keys(parsed)
    return json.dumps(redacted, ensure_ascii=True)

  return text


class RequestLoggingMiddleware:
  """Log request/response details while preserving body streams for downstream handlers."""

  def __init__(self, app: ASGIApp) -> None:
    """Store the downstream ASGI application for request logging."""
    self.app = app

  async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
    """Record request/response metadata without logging request bodies."""
    # Skip non-HTTP scopes to avoid interfering with websocket or lifespan events.
    if scope["type"] != "http":
      await self.app(scope, receive, send)
      return

    # Resolve logging settings once; the cache keeps this cheap per request.
    settings = get_settings()
    log_http_bodies = settings.log_http_bodies
    log_http_body_bytes = settings.log_http_body_bytes

    # Generate a request id and store it for downstream handlers and exception logging.
    request_id = str(uuid.uuid4())
    scope.setdefault("state", {})["request_id"] = request_id

    # Start timing early so latency includes downstream handlers.
    start_time = time.time()
    # Log the incoming request metadata for traceability.
    method = scope.get("method", "UNKNOWN")
    url = _build_request_url(scope)
    logger.info("Incoming request request_id=%s %s %s", request_id, method, url)
    # Log safe request metadata hints without ever touching the body.
    headers = _normalize_headers(scope)
    content_type = headers.get("content-type")
    content_length = headers.get("content-length")
    if content_type or content_length:
      logger.debug("Request metadata request_id=%s content-type=%s content-length=%s", request_id, content_type, content_length)

    # Buffer request bodies only when explicitly enabled.
    request_body = b""
    receive_wrapper = receive
    if log_http_bodies:
      # Drain the incoming body so we can log it and replay for downstream handlers.
      body_chunks: list[bytes] = []
      more_body = True
      while more_body:
        message = await receive()
        if message.get("type") != "http.request":
          break

        chunk = message.get("body", b"")
        if chunk:
          body_chunks.append(chunk)

        more_body = message.get("more_body", False)

      request_body = b"".join(body_chunks)
      # Replay the drained body so request handlers receive the payload as usual.
      body_sent = False

      async def receive_wrapper() -> dict[str, Any]:
        nonlocal body_sent
        if body_sent:
          return {"type": "http.request", "body": b"", "more_body": False}

        body_sent = True
        return {"type": "http.request", "body": request_body, "more_body": False}

      if request_body or content_type:
        formatted_request_body = _format_body_for_log(request_body, content_type, log_http_body_bytes)
        logger.info("Request body request_id=%s body=%s", request_id, formatted_request_body)

    # Capture response status for response timing logs.
    status_code: int | None = None
    response_body_chunks: list[bytes] = []
    response_body_size = 0
    response_body_truncated = False
    response_content_type: str | None = None

    async def send_wrapper(message: dict[str, Any]) -> None:
      # Track the response status from the response start message.
      nonlocal status_code, response_body_size, response_body_truncated, response_content_type
      if message.get("type") == "http.response.start":
        status_code = message.get("status")
        # Attach a request id to responses to correlate clients with server logs.
        response_headers = MutableHeaders(scope=message)
        if "x-request-id" not in response_headers:
          response_headers["x-request-id"] = request_id
        response_content_type = response_headers.get("content-type")

      # Collect response bodies only when explicitly enabled.
      if log_http_bodies and message.get("type") == "http.response.body":
        body_chunk = message.get("body", b"")
        if body_chunk and not response_body_truncated:
          remaining = log_http_body_bytes - response_body_size
          if remaining > 0:
            response_body_chunks.append(body_chunk[:remaining])
            response_body_size += len(body_chunk[:remaining])

          if len(body_chunk) > remaining:
            response_body_truncated = True

        elif body_chunk:
          response_body_truncated = True

      await send(message)

    # Execute downstream handlers to keep middleware focused on observation.
    await self.app(scope, receive_wrapper, send_wrapper)

    # Emit response timing metrics for operational visibility.
    process_time = (time.time() - start_time) * 1000
    response_status = status_code or 0
    logger.info("Response request_id=%s status=%s (took %.2fms)", request_id, response_status, process_time)
    if log_http_bodies and (response_body_chunks or response_content_type):
      response_body = b"".join(response_body_chunks)
      formatted_response_body = _format_body_for_log(response_body, response_content_type, log_http_body_bytes)
      if response_body_truncated:
        formatted_response_body = f"{formatted_response_body}...(truncated)"

      logger.info("Response body request_id=%s status=%s body=%s", request_id, response_status, formatted_response_body)


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
