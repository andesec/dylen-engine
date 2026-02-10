from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from app.core.security import get_current_active_user
from app.main import app
from app.schema.sql import User, UserStatus
from fastapi import HTTPException
from fastapi.testclient import TestClient


class _RepoStub:
  def __init__(self) -> None:
    self.upsert = AsyncMock()
    self.delete_for_user_endpoint = AsyncMock()


def _build_payload(endpoint: str = "https://fcm.googleapis.com/fcm/send/abc") -> dict:
  return {"endpoint": endpoint, "expirationTime": None, "keys": {"p256dh": "BEl6f5Y8X5Y_u7d8mV_AbpZfXfTLT3s1O3L4wM1x8QY2_5qWQ-jxJq7uKjv8mQ4I", "auth": "gq8Yh5xA9l2mQ6pR"}}


def test_push_subscribe_rejects_non_https(monkeypatch):
  app.dependency_overrides[get_current_active_user] = lambda: User(id=uuid.uuid4(), firebase_uid="uid", email="ok@example.com", role_id=uuid.uuid4(), status=UserStatus.APPROVED)
  client = TestClient(app)

  try:
    payload = _build_payload(endpoint="http://fcm.googleapis.com/fcm/send/abc")
    response = client.post("/v1/push/subscribe", json=payload)
    assert response.status_code == 422
  finally:
    app.dependency_overrides.clear()


def test_push_subscribe_rejects_unknown_host(monkeypatch):
  app.dependency_overrides[get_current_active_user] = lambda: User(id=uuid.uuid4(), firebase_uid="uid", email="ok@example.com", role_id=uuid.uuid4(), status=UserStatus.APPROVED)
  client = TestClient(app)

  try:
    payload = _build_payload(endpoint="https://example.com/push/abc")
    response = client.post("/v1/push/subscribe", json=payload)
    assert response.status_code == 422
  finally:
    app.dependency_overrides.clear()


def test_push_subscribe_rejects_invalid_keys(monkeypatch):
  app.dependency_overrides[get_current_active_user] = lambda: User(id=uuid.uuid4(), firebase_uid="uid", email="ok@example.com", role_id=uuid.uuid4(), status=UserStatus.APPROVED)
  client = TestClient(app)

  try:
    payload = _build_payload()
    payload["keys"]["p256dh"] = "not-valid-***"
    response = client.post("/v1/push/subscribe", json=payload)
    assert response.status_code == 422
  finally:
    app.dependency_overrides.clear()


def test_push_subscribe_accepts_valid_payload(monkeypatch):
  repo = _RepoStub()
  user = User(id=uuid.uuid4(), firebase_uid="uid", email="ok@example.com", role_id=uuid.uuid4(), status=UserStatus.APPROVED)

  monkeypatch.setattr("app.api.routes.push.PushSubscriptionRepository", lambda: repo)
  app.dependency_overrides[get_current_active_user] = lambda: user
  client = TestClient(app)

  try:
    response = client.post("/v1/push/subscribe", json=_build_payload(), headers={"user-agent": "dylen-test-agent"})
    assert response.status_code == 204
    repo.upsert.assert_awaited_once()
    entry = repo.upsert.await_args.args[0]
    assert entry.user_id == user.id
    assert entry.endpoint == "https://fcm.googleapis.com/fcm/send/abc"
    assert entry.user_agent == "dylen-test-agent"
  finally:
    app.dependency_overrides.clear()


def test_push_subscribe_truncates_user_agent(monkeypatch):
  repo = _RepoStub()
  user = User(id=uuid.uuid4(), firebase_uid="uid", email="ok@example.com", role_id=uuid.uuid4(), status=UserStatus.APPROVED)

  monkeypatch.setattr("app.api.routes.push.PushSubscriptionRepository", lambda: repo)
  app.dependency_overrides[get_current_active_user] = lambda: user
  client = TestClient(app)

  try:
    very_long_user_agent = "x" * 2000
    response = client.post("/v1/push/subscribe", json=_build_payload(), headers={"user-agent": very_long_user_agent})
    assert response.status_code == 204
    entry = repo.upsert.await_args.args[0]
    assert entry.user_agent is not None
    assert len(entry.user_agent) == 512
  finally:
    app.dependency_overrides.clear()


def test_push_unsubscribe_is_idempotent(monkeypatch):
  repo = _RepoStub()
  user = User(id=uuid.uuid4(), firebase_uid="uid", email="ok@example.com", role_id=uuid.uuid4(), status=UserStatus.APPROVED)

  monkeypatch.setattr("app.api.routes.push.PushSubscriptionRepository", lambda: repo)
  app.dependency_overrides[get_current_active_user] = lambda: user
  client = TestClient(app)

  try:
    response = client.request("DELETE", "/v1/push/unsubscribe", json={"endpoint": "https://fcm.googleapis.com/fcm/send/abc"})
    assert response.status_code == 204
    repo.delete_for_user_endpoint.assert_awaited_once_with(user_id=user.id, endpoint="https://fcm.googleapis.com/fcm/send/abc")
  finally:
    app.dependency_overrides.clear()


def test_push_subscribe_returns_403_for_inactive_override(monkeypatch):
  def _inactive_user():
    raise HTTPException(status_code=403, detail="Inactive user")

  app.dependency_overrides[get_current_active_user] = _inactive_user
  client = TestClient(app)

  try:
    response = client.post("/v1/push/subscribe", json=_build_payload())
    assert response.status_code == 403
  finally:
    app.dependency_overrides.clear()


def test_push_subscribe_returns_401_without_auth_header():
  client = TestClient(app)
  response = client.post("/v1/push/subscribe", json=_build_payload())
  assert response.status_code == 403 or response.status_code == 401
