from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends

from app.ai.agents.research import ResearchAgent
from app.api.deps import consume_research_quota
from app.api.deps_concurrency import verify_concurrency
from app.config import Settings, get_settings
from app.core.security import get_current_active_user, require_feature_flag
from app.jobs.models import JobRecord
from app.schema.research import ResearchDiscoveryRequest, ResearchDiscoveryResponse, ResearchSynthesisRequest, ResearchSynthesisResponse
from app.schema.sql import User
from app.storage.factory import _get_jobs_repo
from app.utils.ids import generate_job_id

router = APIRouter()


def get_research_agent() -> ResearchAgent:
  """Dependency to provide a ResearchAgent instance."""
  return ResearchAgent()


@router.post("/discover", response_model=ResearchDiscoveryResponse, dependencies=[Depends(require_feature_flag("feature.research")), Depends(verify_concurrency("research"))])
async def discover(
  request: ResearchDiscoveryRequest,
  agent: Annotated[ResearchAgent, Depends(get_research_agent)],
  current_user: Annotated[User, Depends(get_current_active_user)],
  quota: Annotated[None, Depends(consume_research_quota)],
  settings: Annotated[Settings, Depends(get_settings)],
) -> ResearchDiscoveryResponse:
  """
  Performs initial web search and returns candidate URLs.
  Requires authentication.
  """
  jobs_repo = _get_jobs_repo(settings)

  if request.idempotency_key:
    existing = await jobs_repo.find_by_idempotency_key(request.idempotency_key)
    if existing and existing.status == "done" and existing.result_json:
      return ResearchDiscoveryResponse.model_validate(existing.result_json)

  tracking_job_id = generate_job_id()
  timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
  job_ttl = int(time.time()) + 3600

  tracking_job = JobRecord(
    job_id=tracking_job_id,
    user_id=str(current_user.id),
    request=request.model_dump(mode="python"),
    status="processing",
    target_agent="research",
    phase="processing",
    created_at=timestamp,
    updated_at=timestamp,
    idempotency_key=request.idempotency_key,
    expected_sections=0,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=0,
    logs=[],
    progress=0.0,
    ttl=job_ttl,
  )
  await jobs_repo.create_job(tracking_job)

  try:
    # Enforce that the discovery is logged for the calling user
    result = await agent.discover(query=request.query, user_id=str(current_user.id), context=request.context)

    await jobs_repo.update_job(tracking_job_id, status="done", phase="done", progress=100.0, completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), result_json=result.model_dump(mode="json"))
    return result
  except Exception as e:
    await jobs_repo.update_job(tracking_job_id, status="error", phase="error", logs=[str(e)], completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    raise


@router.post("/synthesize", response_model=ResearchSynthesisResponse, dependencies=[Depends(require_feature_flag("feature.research")), Depends(verify_concurrency("research"))])
async def synthesize(
  request: ResearchSynthesisRequest, agent: Annotated[ResearchAgent, Depends(get_research_agent)], current_user: Annotated[User, Depends(get_current_active_user)], settings: Annotated[Settings, Depends(get_settings)]
) -> ResearchSynthesisResponse:
  """
  Deep crawls provided URLs and generates a cited report.
  Requires authentication.
  """
  jobs_repo = _get_jobs_repo(settings)

  if request.idempotency_key:
    existing = await jobs_repo.find_by_idempotency_key(request.idempotency_key)
    if existing and existing.status == "done" and existing.result_json:
      return ResearchSynthesisResponse.model_validate(existing.result_json)

  tracking_job_id = generate_job_id()
  timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
  job_ttl = int(time.time()) + 3600

  tracking_job = JobRecord(
    job_id=tracking_job_id,
    user_id=str(current_user.id),
    request=request.model_dump(mode="python"),
    status="processing",
    target_agent="research",
    phase="processing",
    created_at=timestamp,
    updated_at=timestamp,
    idempotency_key=request.idempotency_key,
    expected_sections=0,
    completed_sections=0,
    completed_section_indexes=[],
    retry_count=0,
    max_retries=0,
    logs=[],
    progress=0.0,
    ttl=job_ttl,
  )
  await jobs_repo.create_job(tracking_job)

  try:
    # Enforce that the synthesis is logged for the calling user
    result = await agent.synthesize(query=request.query, urls=request.urls, user_id=str(current_user.id))

    await jobs_repo.update_job(tracking_job_id, status="done", phase="done", progress=100.0, completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), result_json=result.model_dump(mode="json"))
    return result
  except Exception as e:
    await jobs_repo.update_job(tracking_job_id, status="error", phase="error", logs=[str(e)], completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    raise
