from __future__ import annotations

import uuid

from app.core.security import get_current_active_user
from app.main import app
from app.schema.sql import User, UserStatus
from fastapi import HTTPException
from fastapi.testclient import TestClient

_VALID_SUBSCRIPTION = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "expirationTime": None, "keys": {"p256dh": "BEl6f5Y8X5Y_u7d8mV_AbpZfXfTLT3s1O3L4wM1x8QY2_5qWQ-jxJq7uKjv8mQ4I", "auth": "gq8Yh5xA9l2mQ6pR"}}


def test_subscribe_requires_auth():
  client = TestClient(app)
  response = client.post("/v1/push/subscribe", json=_VALID_SUBSCRIPTION)
  assert response.status_code == 401


def test_subscribe_forbidden_for_inactive_user_override():
  def _inactive_user():
    raise HTTPException(status_code=403, detail="Inactive user")

  app.dependency_overrides[get_current_active_user] = _inactive_user
  client = TestClient(app)

  try:
    response = client.post("/v1/push/subscribe", json=_VALID_SUBSCRIPTION)
    assert response.status_code == 403
  finally:
    app.dependency_overrides.clear()


def test_subscribe_and_unsubscribe_happy_path(monkeypatch):
  class _RepoStub:
    async def upsert(self, entry):
      return None

    async def delete_for_user_endpoint(self, *, user_id, endpoint):
      return None

  monkeypatch.setattr("app.api.routes.push.PushSubscriptionRepository", lambda: _RepoStub())
  app.dependency_overrides[get_current_active_user] = lambda: User(id=uuid.uuid4(), firebase_uid="uid", email="ok@example.com", role_id=uuid.uuid4(), status=UserStatus.APPROVED)
  client = TestClient(app)

  try:
    subscribe_response = client.post("/v1/push/subscribe", json=_VALID_SUBSCRIPTION)
    assert subscribe_response.status_code == 204

    unsubscribe_response = client.request("DELETE", "/v1/push/unsubscribe", json={"endpoint": _VALID_SUBSCRIPTION["endpoint"]})
    assert unsubscribe_response.status_code == 204
  finally:
    app.dependency_overrides.clear()
