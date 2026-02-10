"""Retry logic with specific backoff strategy."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TypeVar

T = TypeVar("T")
logger = logging.getLogger(__name__)


async def retry_with_backoff(func, *args, **kwargs) -> T:
  """
  Execute a function with retries only for explicit 429 rate-limit errors.
  """
  max_retries = 3
  base_delay = 1.0
  for attempt in range(max_retries):
    try:
      return await func(*args, **kwargs)
    except Exception as e:
      error_msg = str(e)
      is_rate_limit = "429" in error_msg or "Too Many Requests" in error_msg
      if not is_rate_limit:
        raise
      delay = (base_delay * (2**attempt)) + random.uniform(0.0, 0.5)
      logger.warning(f"429 retry attempt {attempt + 1}/{max_retries}. Retrying in {delay:.2f}s. Error: {error_msg}")
      await asyncio.sleep(delay)
  return await func(*args, **kwargs)
