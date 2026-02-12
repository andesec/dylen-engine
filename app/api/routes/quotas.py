from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_quota
from app.core.security import require_permission
from app.services.quotas import ResolvedQuota, get_quota_resource

router = APIRouter()


@router.get("/quota/{resource}", dependencies=[Depends(require_permission("user:quota_read"))])
async def get_quota_resource_by_key(resource: str, quota: ResolvedQuota = Depends(get_quota)) -> dict[str, Any]:  # noqa: B008
  """Return a single quota resource payload for the authenticated user."""
  # Resolve a targeted quota entry so UIs can fetch one resource without full payloads.
  resolved = get_quota_resource(quota, resource=resource)
  if not resolved:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"error": "QUOTA_NOT_AVAILABLE", "message": "Requested quota is not available. Please contact your administrator."})
  return {"tier_name": quota.tier_name, "quota": resolved}
