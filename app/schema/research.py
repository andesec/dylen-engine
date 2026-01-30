from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class CandidateSource(BaseModel):
  """A candidate source found during the discovery phase."""

  title: StrictStr
  url: StrictStr
  snippet: StrictStr
  model_config = ConfigDict(extra="ignore")


class ResearchDiscoveryRequest(BaseModel):
  """Request to discover sources for a research topic."""

  query: StrictStr = Field(..., min_length=1, description="The research query.")
  context: StrictStr | None = Field(default=None, description="Optional context to refine the search.")
  model_config = ConfigDict(extra="forbid")


class ResearchDiscoveryResponse(BaseModel):
  """Response containing discovered candidate sources."""

  sources: list[CandidateSource]


class ResearchSynthesisRequest(BaseModel):
  """Request to synthesize a report from selected URLs."""

  query: StrictStr = Field(..., min_length=1, description="The original research query.")
  urls: list[StrictStr] = Field(..., min_length=1, description="List of URLs to crawl and synthesize.")
  user_id: StrictStr = Field(..., description="User ID for audit logging.")
  model_config = ConfigDict(extra="forbid")


class ResearchSynthesisResponse(BaseModel):
  """The synthesized research report."""

  answer: StrictStr
  sources: list[dict[str, Any]]
