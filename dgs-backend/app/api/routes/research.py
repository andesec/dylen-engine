from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from crawl4ai import AsyncWebCrawler
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from firebase_admin import firestore
from google import genai
from tavily import TavilyClient

from app.config import get_settings
from app.schema.research import CandidateSource, ResearchDiscoveryRequest, ResearchDiscoveryResponse, ResearchSynthesisRequest, ResearchSynthesisResponse

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def _get_gemini_client() -> genai.Client:
  api_key = os.getenv("GEMINI_API_KEY")
  if not api_key:
    raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
  return genai.Client(api_key=api_key)


def _get_tavily_client() -> TavilyClient:
  if not settings.tavily_api_key:
    raise HTTPException(status_code=500, detail="TAVILY_API_KEY not configured")
  return TavilyClient(api_key=settings.tavily_api_key)


async def _classify_query(client: genai.Client, query: str) -> str:
  """Classify the query into General, Academic, Security, or News."""
  prompt = f"""Classify the following query into one of these categories: General, Academic, Security, News.
Return ONLY the category name.

Query: {query}"""
  try:
    response = await client.aio.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    category = response.text.strip()
    # Fallback if model chats too much, though 2.5-flash is usually concise.
    for cat in ["General", "Academic", "Security", "News"]:
      if cat.lower() in category.lower():
        return cat
    return "General"
  except Exception as e:
    logger.error(f"Router LLM failed: {e}")
    return "General"


@router.post("/discover", response_model=ResearchDiscoveryResponse)
async def discover(request: ResearchDiscoveryRequest) -> ResearchDiscoveryResponse:
  """Performs initial web search and returns candidate URLs."""
  gemini_client = _get_gemini_client()
  tavily_client = _get_tavily_client()

  # 1. Router
  category = await _classify_query(gemini_client, request.query)
  logger.info(f"Query classified as: {category}")

  # 2. Domain Filtering & Query Adjustment
  search_query = request.query
  if category == "Security":
    search_query += " site:github.com OR site:nvd.nist.gov"
  elif category == "Academic":
    search_query += " site:*.edu OR site:arxiv.org"

  # 3. Search Engine
  try:
    # Tavily client is sync, run in threadpool
    search_result = await run_in_threadpool(tavily_client.search, query=search_query, search_depth="basic", include_answer=False, include_raw_content=False, max_results=5)
  except Exception as e:
    logger.error(f"Tavily search failed: {e}")
    raise HTTPException(status_code=502, detail="Search engine failed") from e

  candidates = []
  for result in search_result.get("results", []):
    candidates.append(CandidateSource(title=result.get("title", ""), url=result.get("url", ""), snippet=result.get("content", "")))

  return ResearchDiscoveryResponse(sources=candidates)


@router.post("/synthesize", response_model=ResearchSynthesisResponse)
async def synthesize(request: ResearchSynthesisRequest) -> ResearchSynthesisResponse:
  """Deep crawls provided URLs and generates a cited report."""
  if not request.urls:
    raise HTTPException(status_code=400, detail="No URLs provided")

  # 1. Crawl Phase
  crawled_data: list[dict[str, Any]] = []

  # Crawl4AI usage
  try:
    async with AsyncWebCrawler(verbose=True) as crawler:
      # Run sequentially or gather? Spec says concurrently.
      # crawler.arun is async.
      tasks = [crawler.arun(url=url) for url in request.urls]
      results = await asyncio.gather(*tasks, return_exceptions=True)

      for i, result in enumerate(results):
        if isinstance(result, Exception):
          logger.error(f"Failed to crawl {request.urls[i]}: {result}")
          continue

        if not result.success:
          logger.warning(f"Crawl failed for {request.urls[i]}: {result.error_message}")
          continue

        crawled_data.append(
          {
            "url": request.urls[i],
            "markdown": result.markdown,
            "title": request.urls[i],  # Fallback title or extract from result if available? result doesn't seem to have title field easily accessible in simple docs, usually metadata.
          }
        )
  except Exception as e:
    logger.error(f"Crawling failed: {e}")
    # Continue with whatever we have or fail? Spec says "If a URL fails to crawl, skip it".
    pass

  if not crawled_data:
    raise HTTPException(status_code=502, detail="Failed to crawl any sources")

  # 2. Context Assembly
  context_parts = []
  sources_out = []
  for i, data in enumerate(crawled_data):
    idx = i + 1
    # Safety check: simplistic script tag removal (though markdown usually safe)
    safe_markdown = data["markdown"].replace("<script", "&lt;script").replace("</script>", "&lt;/script&gt;")

    context_parts.append(f"[Source #{idx}: {data['url']}]\n{safe_markdown}\n")
    sources_out.append({"title": f"Source #{idx}", "url": data["url"]})

  full_context = "\n".join(context_parts)

  # 3. Prompting
  prompt = f"""Synthesize an answer using ONLY the provided context.
Use numeric citations [{1}].
Format the output in clean Markdown.

Query: {request.query}

Context:
{full_context}"""

  # 4. LLM Synthesis
  gemini_client = _get_gemini_client()
  try:
    # Spec says Gemini-1.5-Pro.
    response = await gemini_client.aio.models.generate_content(model="gemini-1.5-pro", contents=prompt)
    answer = response.text
  except Exception as e:
    logger.error(f"Synthesis LLM failed: {e}")
    raise HTTPException(status_code=502, detail="Synthesis failed") from e

  # 5. Storage (Firestore)
  try:
    # Run firestore in threadpool as it is blocking or check if async client available.
    # firebase_admin.firestore.client() returns a sync client.
    # There is an async client for firestore in google-cloud-firestore but we use firebase-admin.
    # We'll use run_in_threadpool.
    await run_in_threadpool(_log_to_firestore, request.user_id, request.query, sources_out)
  except Exception as e:
    logger.error(f"Firestore logging failed: {e}")
    # Don't fail the request if logging fails

  return ResearchSynthesisResponse(answer=answer, sources=sources_out)


def _log_to_firestore(user_id: str, query: str, sources: list[dict[str, Any]]) -> None:
  """Logs the research synthesis to Firestore."""
  try:
    db = firestore.client()
    # Public Metadata
    # /artifacts/{appId}/public/data/research_logs
    # Assuming appId is 'dgs' or similar. Spec says {appId}.
    app_id = "dgs"  # Default

    # User Sessions
    # /artifacts/{appId}/users/{userId}/search_history

    timestamp = datetime.now(datetime.UTC)

    # Log to public metadata (maybe just summary?)
    # Spec says: Storage Paths (Rule 1 Compliance)
    # Public Metadata: /artifacts/{appId}/public/data/research_logs
    # User Sessions: /artifacts/{appId}/users/{userId}/search_history

    # Since this is a list, maybe we add a document to this collection?
    # Firestore structure: Collection -> Document

    # Log to Public
    public_ref = db.collection("artifacts").document(app_id).collection("public").document("data").collection("research_logs")
    public_ref.add({"query": query, "sources": sources, "timestamp": timestamp, "user_id": user_id})

    # Log to User
    user_ref = db.collection("artifacts").document(app_id).collection("users").document(user_id).collection("search_history")
    user_ref.add({"query": query, "sources": sources, "timestamp": timestamp})

  except Exception as e:
    logger.error(f"Failed to log to Firestore: {e}")
    raise
