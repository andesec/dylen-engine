"""Research agent implementation."""

from __future__ import annotations

import ipaddress
import logging
import socket
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from fastapi.concurrency import run_in_threadpool
from firebase_admin import firestore

from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.tavily import TavilyProvider
from app.config import get_settings
from app.schema.research import CandidateSource, ResearchDiscoveryResponse, ResearchSynthesisResponse
from app.services.runtime_config import get_research_model, get_research_router_model

logger = logging.getLogger(__name__)


class ResearchAgent:
  """Agent responsible for research tasks: discovery and synthesis."""

  def __init__(self) -> None:
    settings = get_settings()
    self.gemini_provider = GeminiProvider(api_key=settings.gemini_api_key)
    self.tavily_provider = TavilyProvider()
    self.search_max_results = settings.research_search_max_results

  async def discover(self, query: str, user_id: str, context: str | None = None, runtime_config: dict[str, Any] | None = None) -> ResearchDiscoveryResponse:
    """
    Discover sources for a given query.

    1. Classify intent.
    2. Enhance query.
    3. Search Tavily.
    4. Log to Firestore.
    """
    # Get model config from runtime config (with fallbacks)
    if runtime_config is None:
      runtime_config = {}

    _synthesis_provider, _synthesis_model = get_research_model(runtime_config)
    _router_provider, router_model_name = get_research_router_model(runtime_config)
    # 1. Router
    category = await self._classify_query(query, router_model_name)
    logger.info(f"Query classified as: {category}")

    # 2. Domain Filtering & Query Adjustment
    search_query = query
    if category == "Security":
      search_query += " site:github.com OR site:nvd.nist.gov"
    elif category == "Academic":
      search_query += " site:*.edu OR site:arxiv.org"

    if context:
      search_query += f" {context}"

    # 3. Search Engine
    try:
      search_result = await self.tavily_provider.search(query=search_query, search_depth="basic", include_answer=False, include_raw_content=False, max_results=self.search_max_results)
    except Exception as e:
      logger.error(f"Discovery search failed: {e}")
      # Fail gracefully? Or re-raise?
      raise RuntimeError(f"Search failed: {e}") from e

    candidates = []
    for result in search_result.get("results", []):
      candidates.append(CandidateSource(title=result.get("title", ""), url=result.get("url", ""), snippet=result.get("content", "")))

    # 4. Log to Firestore
    try:
      # We log the raw search result or the candidates. Logging candidates is cleaner.
      log_entry = {"action": "discover", "query": query, "context": context, "category": category, "search_query": search_query, "candidates": [c.model_dump() for c in candidates]}
      await run_in_threadpool(self._log_to_firestore, user_id=user_id, data=log_entry)
    except Exception as e:
      logger.error(f"Firestore logging for discover failed: {e}")

    return ResearchDiscoveryResponse(sources=candidates)

  async def synthesize(self, query: str, urls: list[str], user_id: str, runtime_config: dict[str, Any] | None = None) -> ResearchSynthesisResponse:
    """
    Synthesize a report from the provided URLs.

    1. Crawl URLs.
    2. Assemble context.
    3. Generate report.
    4. Log to Firestore.
    """
    # Get model config from runtime config (with fallbacks)
    if runtime_config is None:
      runtime_config = {}

    synthesis_provider, synthesis_model_name = get_research_model(runtime_config)
    _router_provider, _router_model = get_research_router_model(runtime_config)
    # 1. Crawl Phase
    crawled_data = await self._crawl_urls(urls)

    if not crawled_data:
      raise RuntimeError("Failed to crawl any sources.")

    # 2. Context Assembly
    context_parts = []
    sources_out = []
    for i, data in enumerate(crawled_data):
      idx = i + 1
      # Basic sanitization
      safe_markdown = data["markdown"].replace("<script", "&lt;script").replace("</script>", "&lt;/script&gt;")

      context_parts.append(f"[Source #{idx}: {data['url']}]\n{safe_markdown}\n")
      sources_out.append({"title": f"Source #{idx}", "url": data["url"]})

    full_context = "\n".join(context_parts)

    # 3. Prompting
    prompt = f"""Synthesize an answer using ONLY the provided context.
Use numeric citations like [1] in the text.
Format the output in clean Markdown.

Query: {query}

Context:
{full_context}"""

    # 4. LLM Synthesis
    try:
      model = self.gemini_provider.get_model(synthesis_model_name)
      response = await model.generate(prompt)
      answer = response.content

      # Log usage if available
      if response.usage:
        logger.info(f"Synthesis usage: {response.usage}")

    except Exception as e:
      logger.error(f"Synthesis generation failed: {e}")
      raise RuntimeError(f"Synthesis failed: {e}") from e

    # 5. Storage (Firestore)
    try:
      log_entry = {"action": "synthesize", "query": query, "sources": sources_out}
      await run_in_threadpool(self._log_to_firestore, user_id=user_id, data=log_entry)
    except Exception as e:
      logger.error(f"Firestore logging failed: {e}")
      # We don't fail the request if logging fails, but we log the error.

    return ResearchSynthesisResponse(answer=answer, sources=sources_out)

  async def _classify_query(self, query: str, router_model_name: str) -> str:
    """Classify the query into General, Academic, Security, or News."""
    prompt = f"""Classify the following query into one of these categories: General, Academic, Security, News.
Return ONLY the category name.

Query: {query}"""
    try:
      model = self.gemini_provider.get_model(router_model_name)
      response = await model.generate(prompt)
      category = response.content.strip()

      # Clean up potential extra text if the model is chatty
      # We expect just the word.
      import re

      match = re.search(r"\b(General|Academic|Security|News)\b", category, re.IGNORECASE)
      if match:
        # Return the canonical case
        return match.group(1).capitalize()

      return "General"

    except Exception as e:
      logger.error(f"Router LLM failed: {e}")
      return "General"

  async def _crawl_urls(self, urls: list[str]) -> list[dict[str, Any]]:
    crawled_data = []

    # Fallback to Tavily specifically requested to avoid heavy crawl4ai dependencies
    try:
      for url in urls:
        if not await self._is_safe_url(url):
          logger.warning(f"Skipping unsafe URL: {url}")
          continue

        try:
          fallback_data = await self._fetch_content_tavily(url)
          if fallback_data:
            crawled_data.append(fallback_data)
        except Exception as e:
          logger.error(f"Individual crawl failed for {url}: {e}")
          # functionality continues for other URLs
    except Exception as e:
      logger.error(f"Critical crawling phase failed: {e}")
      # Proceed if we have any data, otherwise this might result in empty context later
      pass

    return crawled_data

  async def _fetch_content_tavily(self, url: str) -> dict[str, Any] | None:
    """Fetch content for a URL using Tavily as a fallback."""
    try:
      # Use Tavily to 'search' for the specific URL to get its content context
      # We search for the URL itself.
      response = await self.tavily_provider.search(
        query=url,
        search_depth="advanced",  # Use advanced to extract more content?
        include_raw_content=False,  # We want the 'content' field which is a summary/snippet, or maybe raw if needed.
        # Tavily 'content' field is usually good enough.
        max_results=1,
      )
      results = response.get("results", [])
      if results:
        result = results[0]
        content = result.get("content", "")
        title = result.get("title", url)  # Fallback to URL if title missing
        return {"url": url, "markdown": content, "title": title}
    except Exception as e:
      logger.error(f"Tavily fallback failed for {url}: {e}")
    return None

  async def _is_safe_url(self, url: str) -> bool:
    """Check if a URL is safe to crawl (no private/internal IPs)."""
    return await run_in_threadpool(self._validate_url_sync, url)

  def _validate_url_sync(self, url: str) -> bool:
    try:
      parsed = urlparse(url)
      if parsed.scheme not in ("http", "https"):
        return False

      hostname = parsed.hostname
      if not hostname:
        return False

      # Resolve hostname to IP
      try:
        ip = socket.gethostbyname(hostname)
      except socket.gaierror:
        return False

      # Check for private IP
      ip_obj = ipaddress.ip_address(ip)
      if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
        return False

      return True
    except Exception:
      return False

  def _log_to_firestore(self, user_id: str, data: dict[str, Any]) -> None:
    """Logs the research activity to Firestore."""
    try:
      db = firestore.client()
      app_id = "dylen"
      timestamp = datetime.now(datetime.UTC)

      payload = {**data, "timestamp": timestamp, "user_id": user_id}

      # Log to Public (Exclude PII)
      # Create a safe payload for public logging
      public_payload = {k: v for k, v in payload.items() if k != "user_id"}

      public_ref = db.collection("artifacts").document(app_id).collection("public").document("data").collection("research_logs")
      public_ref.add(public_payload)

      # Log to User
      user_ref = db.collection("artifacts").document(app_id).collection("users").document(user_id).collection("search_history")
      user_ref.add(payload)
    except Exception as e:
      logger.error(f"Failed to log to Firestore: {e}")
      raise
