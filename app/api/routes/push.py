"""Routes for Web Push subscription lifecycle management."""

from __future__ import annotations

import re
import urllib.parse

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.core.security import get_current_active_user
from app.notifications.push_subscription_repo import PushSubscriptionEntry, PushSubscriptionRepository
from app.schema.sql import User

_ALLOWED_PUSH_HOSTS = {"fcm.googleapis.com", "updates.push.services.mozilla.com", "push.services.mozilla.com", "web.push.apple.com"}
_BASE64_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")

router = APIRouter()


class PushSubscriptionKeys(BaseModel):
  """Browser-provided key material for Web Push encryption."""

  p256dh: str = Field(min_length=40, max_length=512)
  auth: str = Field(min_length=16, max_length=256)
  model_config = ConfigDict(extra="forbid")

  @field_validator("p256dh")
  @classmethod
  def validate_p256dh(cls, value: str) -> str:
    """Validate p256dh key shape using a strict base64url policy."""
    normalized = value.strip()
    if len(normalized) < 40:
      raise PydanticCustomError("push_p256dh_short", "p256dh key is too short.")

    if not _BASE64_RE.fullmatch(normalized):
      raise PydanticCustomError("push_p256dh_format", "p256dh must be base64url encoded.")

    return normalized

  @field_validator("auth")
  @classmethod
  def validate_auth(cls, value: str) -> str:
    """Validate auth secret shape using a strict base64url policy."""
    normalized = value.strip()
    if len(normalized) < 16:
      raise PydanticCustomError("push_auth_short", "auth key is too short.")

    if not _BASE64_RE.fullmatch(normalized):
      raise PydanticCustomError("push_auth_format", "auth must be base64url encoded.")

    return normalized


class PushSubscribeRequest(BaseModel):
  """Standard browser push subscription object payload."""

  endpoint: str = Field(min_length=1, max_length=2048)
  expiration_time: int | None = Field(default=None, alias="expirationTime")
  keys: PushSubscriptionKeys
  model_config = ConfigDict(extra="forbid", populate_by_name=True)

  @field_validator("endpoint")
  @classmethod
  def validate_endpoint(cls, value: str) -> str:
    """Restrict endpoints to known provider hosts over HTTPS."""
    normalized = value.strip()
    parsed = urllib.parse.urlparse(normalized)

    if parsed.scheme.lower() != "https":
      raise PydanticCustomError("push_endpoint_https", "endpoint must use https.")

    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_PUSH_HOSTS:
      raise PydanticCustomError("push_endpoint_host", "endpoint host is not allowed.")

    return normalized


class PushUnsubscribeRequest(BaseModel):
  """Payload for deleting an existing push subscription."""

  endpoint: str = Field(min_length=1, max_length=2048)
  model_config = ConfigDict(extra="forbid")

  @field_validator("endpoint")
  @classmethod
  def validate_endpoint(cls, value: str) -> str:
    """Apply the same strict endpoint validation as subscribe."""
    normalized = value.strip()
    parsed = urllib.parse.urlparse(normalized)

    if parsed.scheme.lower() != "https":
      raise PydanticCustomError("push_endpoint_https", "endpoint must use https.")

    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_PUSH_HOSTS:
      raise PydanticCustomError("push_endpoint_host", "endpoint host is not allowed.")

    return normalized


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe_to_push(payload: PushSubscribeRequest, response: Response, current_user: User = Depends(get_current_active_user), user_agent: str | None = Header(default=None)) -> Response:  # noqa: B008
  """Upsert the authenticated user's browser push subscription."""
  normalized_user_agent = None
  if user_agent:
    # Clamp user agent size to reduce storage abuse while keeping device context.
    normalized_user_agent = user_agent.strip()[:512] or None

  # Persist the device subscription keyed by endpoint.
  try:
    await PushSubscriptionRepository().upsert(PushSubscriptionEntry(user_id=current_user.id, endpoint=payload.endpoint, p256dh=payload.keys.p256dh, auth=payload.keys.auth, user_agent=normalized_user_agent))
  except Exception as exc:  # noqa: BLE001
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save push subscription") from exc

  response.status_code = status.HTTP_204_NO_CONTENT
  return response


@router.delete("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_from_push(payload: PushUnsubscribeRequest, response: Response, current_user: User = Depends(get_current_active_user)) -> Response:  # noqa: B008
  """Delete a push subscription owned by the authenticated user."""
  # Delete by user and endpoint while keeping the operation idempotent.
  try:
    await PushSubscriptionRepository().delete_for_user_endpoint(user_id=current_user.id, endpoint=payload.endpoint)
  except Exception as exc:  # noqa: BLE001
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete push subscription") from exc

  response.status_code = status.HTTP_204_NO_CONTENT
  return response
