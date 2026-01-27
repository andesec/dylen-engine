"""Research agent implementation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from crawl4ai import AsyncWebCrawler
from fastapi.concurrency import run_in_threadpool
from firebase_admin import firestore

from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.tavily import TavilyProvider
from app.config import get_settings
from app.schema.research import CandidateSource, ResearchDiscoveryResponse, ResearchSynthesisResponse

logger = logging.getLogger(__name__)


class ResearchAgent:
  """Agent responsible for research tasks: discovery and synthesis."""

  def __init__(self) -> None:
    settings = get_settings()
    # Initialize providers
    # We could allow passing these in for testing, but for now we instantiate them.
    # In a real DI system we'd pass them.
    self.gemini_provider = GeminiProvider()
    self.tavily_provider = TavilyProvider()

    # Models
    self.synthesis_model_name = settings.research_model or "gemini-1.5-pro"
    self.router_model_name = "gemini-1.5-flash"  # Fast model for routing

  async def discover(self, query: str, context: str | None = None) -> ResearchDiscoveryResponse:
    """
    Discover sources for a given query.

    1. Classify intent.
    2. Enhance query.
    3. Search Tavily.
    """
    # 1. Router
    category = await self._classify_query(query)
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
      search_result = await self.tavily_provider.search(query=search_query, search_depth="basic", include_answer=False, include_raw_content=False, max_results=5)
    except Exception as e:
      logger.error(f"Discovery search failed: {e}")
      # Fail gracefully? Or re-raise?
      raise RuntimeError(f"Search failed: {e}") from e

    candidates = []
    for result in search_result.get("results", []):
      candidates.append(CandidateSource(title=result.get("title", ""), url=result.get("url", ""), snippet=result.get("content", "")))

    return ResearchDiscoveryResponse(sources=candidates)

  async def synthesize(self, query: str, urls: list[str], user_id: str) -> ResearchSynthesisResponse:
    """
    Synthesize a report from the provided URLs.

    1. Crawl URLs.
    2. Assemble context.
    3. Generate report.
    4. Log to Firestore.
    """
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
Use numeric citations [{1}].
Format the output in clean Markdown.

Query: {query}

Context:
{full_context}"""

    # 4. LLM Synthesis
    try:
      model = self.gemini_provider.get_model(self.synthesis_model_name)
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
      await run_in_threadpool(self._log_to_firestore, user_id, query, sources_out)
    except Exception as e:
      logger.error(f"Firestore logging failed: {e}")
      # We don't fail the request if logging fails, but we log the error.

    return ResearchSynthesisResponse(answer=answer, sources=sources_out)

  async def _classify_query(self, query: str) -> str:
    """Classify the query into General, Academic, Security, or News."""
    prompt = f"""Classify the following query into one of these categories: General, Academic, Security, News.
Return ONLY the category name.

Query: {query}"""
    try:
      model = self.gemini_provider.get_model(self.router_model_name)
      response = await model.generate(prompt)
      category = response.content.strip()

      # Fallback logic
      for cat in ["General", "Academic", "Security", "News"]:
        if cat.lower() in category.lower():
          return cat
      return "General"
    except Exception as e:
      logger.error(f"Router LLM failed: {e}")
      return "General"

  async def _crawl_urls(self, urls: list[str]) -> list[dict[str, Any]]:
    crawled_data = []
    try:
      async with AsyncWebCrawler(verbose=True) as crawler:
        tasks = [crawler.arun(url=url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
          if isinstance(result, Exception):
            logger.error(f"Failed to crawl {urls[i]}: {result}")
            continue

          if not result.success:
            logger.warning(f"Crawl failed for {urls[i]}: {result.error_message}")
            continue

          crawled_data.append({"url": urls[i], "markdown": result.markdown})
    except Exception as e:
      logger.error(f"Crawling process failed: {e}")

    return crawled_data

  def _log_to_firestore(self, user_id: str, query: str, sources: list[dict[str, Any]]) -> None:
    """Logs the research synthesis to Firestore."""
    try:
      db = firestore.client()
      app_id = "dgs"
      timestamp = datetime.now(datetime.UTC)

      # Log to Public
      public_ref = db.collection("artifacts").document(app_id).collection("public").document("data").collection("research_logs")
      public_ref.add({"query": query, "sources": sources, "timestamp": timestamp, "user_id": user_id})

      # Log to User
      user_ref = db.collection("artifacts").document(app_id).collection("users").document(user_id).collection("search_history")
      user_ref.add({"query": query, "sources": sources, "timestamp": timestamp})
    except Exception as e:
      logger.error(f"Failed to log to Firestore: {e}")
      raise
