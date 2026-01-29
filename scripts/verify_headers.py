"""Header verification helper used in container debugging.

This script performs an HTTP request and prints response headers to help debug CORS.
It validates the request URL and Origin header to ensure only http/https values are used.
"""

import os
import urllib.error
import urllib.request
from urllib.parse import urlparse


def _require_http_url(value: str, *, field_name: str) -> str:
  """Validate that a value is an http(s) URL suitable for network use."""
  # Normalize whitespace to avoid bypasses via surrounding spaces/newlines.
  candidate = value.strip()
  parsed = urlparse(candidate)

  # Only allow http(s) to avoid unexpected schemes.
  if parsed.scheme not in {"http", "https"}:
    raise ValueError(f"{field_name} must start with http:// or https://")

  # Require a network location to avoid malformed URLs like http:///path.
  if not parsed.netloc:
    raise ValueError(f"{field_name} must include a hostname.")

  return candidate


print("--- Testing Connectivity from within container ---")
try:
  url = _require_http_url("http://localhost:8002/v1/lessons/catalog", field_name="url")
  print(f"Requesting: {url}")

  req = urllib.request.Request(url)

  # Use the first allowed origin from environment variables, or fallback to a default
  allowed_origins = os.getenv("DYLEN_ALLOWED_ORIGINS", "https://app.dylen.orb.local")
  origin = _require_http_url(allowed_origins.split(",")[0], field_name="Origin")

  req.add_header("Origin", origin)

  with urllib.request.urlopen(req) as response:
    print(f"Status: {response.getcode()}")
    print("Headers:")
    for k, v in response.headers.items():
      print(f"{k}: {v}")

except urllib.error.HTTPError as e:
  print(f"HTTPError: {e.code} {e.reason}")
  print("Headers:")
  for k, v in e.headers.items():
    print(f"{k}: {v}")
except Exception as e:
  print(f"Error: {e}")
