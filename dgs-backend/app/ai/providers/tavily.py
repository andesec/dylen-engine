"""Tavily search provider implementation."""

from __future__ import annotations

import logging
from typing import Any

from fastapi.concurrency import run_in_threadpool
from tavily import TavilyClient

from app.config import get_settings

logger = logging.getLogger(__name__)


class TavilyProvider:
  """Provider for Tavily search API."""

  def __init__(self, api_key: str | None = None) -> None:
    settings = get_settings()
    self._api_key = api_key or settings.tavily_api_key
    if not self._api_key:
      raise ValueError("Tavily API key is required.")
    self._client = TavilyClient(api_key=self._api_key)

  async def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
    """
    Perform a search using Tavily.

    Args:
        query: The search query.
        **kwargs: Additional arguments passed to TavilyClient.search (e.g., search_depth, max_results).

    Returns:
        The search response dictionary.
    """
    try:
      # Tavily client is synchronous
      response = await run_in_threadpool(self._client.search, query=query, **kwargs)
      logger.info(f"Tavily search performed for query: '{query}'")
      return response
    except Exception as e:
      logger.error(f"Tavily search failed: {e}")
      raise
