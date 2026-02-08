"""Retry logic with specific backoff strategy."""

from __future__ import annotations

import asyncio
import logging
from typing import TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


async def retry_with_backoff(func, *args, **kwargs) -> T:
  """
  Execute a function with retries for specific 429/Quota errors.

  Delays: 5s, 20s, 50s.
  """
  # Delays in seconds
  delays = [5, 20, 50]

  for attempt, delay in enumerate(delays):
    try:
      return await func(*args, **kwargs)
    except Exception as e:
      error_msg = str(e)
      # Check for 429 or Quota errors
      is_quota_error = "Resource Exhausted" in error_msg or "Quota Exceeded" in error_msg
      is_rate_limit = "429" in error_msg or "Too Many Requests" in error_msg

      if is_quota_error or is_rate_limit:
        logger.warning(f"Retry attempt {attempt + 1}/{len(delays)} needed. Error: {error_msg}. Retrying in {delay}s...")
        await asyncio.sleep(delay)
      else:
        # Non-retryable error, raise immediately
        raise

  # Final attempt
  return await func(*args, **kwargs)
