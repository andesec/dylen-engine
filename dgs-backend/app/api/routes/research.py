from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.ai.agents.research import ResearchAgent
from app.api.deps import consume_research_quota, get_current_active_user
from app.schema.research import ResearchDiscoveryRequest, ResearchDiscoveryResponse, ResearchSynthesisRequest, ResearchSynthesisResponse
from app.schema.sql import User

router = APIRouter()


def get_research_agent() -> ResearchAgent:
  """Dependency to provide a ResearchAgent instance."""
  return ResearchAgent()


@router.post("/discover", response_model=ResearchDiscoveryResponse)
async def discover(
  request: ResearchDiscoveryRequest, agent: Annotated[ResearchAgent, Depends(get_research_agent)], current_user: Annotated[User, Depends(get_current_active_user)], quota: Annotated[None, Depends(consume_research_quota)]
) -> ResearchDiscoveryResponse:
  """
  Performs initial web search and returns candidate URLs.
  Requires authentication.
  """
  # Enforce that the discovery is logged for the calling user
  return await agent.discover(query=request.query, user_id=str(current_user.id), context=request.context)


@router.post("/synthesize", response_model=ResearchSynthesisResponse)
async def synthesize(request: ResearchSynthesisRequest, agent: Annotated[ResearchAgent, Depends(get_research_agent)], current_user: Annotated[User, Depends(get_current_active_user)]) -> ResearchSynthesisResponse:
  """
  Deep crawls provided URLs and generates a cited report.
  Requires authentication.
  """
  # Enforce that the synthesis is logged for the calling user
  return await agent.synthesize(query=request.query, urls=request.urls, user_id=str(current_user.id))
