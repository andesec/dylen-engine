import uuid
from unittest.mock import AsyncMock, MagicMock

import brotli
import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import get_current_identity
from app.main import app
from app.schema.fenster import FensterWidgetType
from app.schema.sql import UserStatus


@pytest.fixture
def client():
  return TestClient(app)


@pytest.fixture
def mock_db():
  return AsyncMock()


def test_fenster_unauthorized(client):
  # No auth header
  response = client.get("/api/v1/fenster/some-id")
  # 401 because HTTPBearer dependency fails (missing token)
  assert response.status_code == 401


def test_fenster_forbidden_free_tier(client, mock_db):
  user = MagicMock()
  user.status = UserStatus.APPROVED
  user.id = uuid.uuid4()
  claims = {"tier": "Free"}

  app.dependency_overrides[get_current_identity] = lambda: (user, claims)
  app.dependency_overrides[get_db] = lambda: mock_db

  try:
    response = client.get(f"/api/v1/fenster/{uuid.uuid4()}")
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "UPGRADE_REQUIRED"
  finally:
    del app.dependency_overrides[get_current_identity]
    del app.dependency_overrides[get_db]


@pytest.mark.anyio
async def test_fenster_success_inline(client, mock_db, monkeypatch):
  async def _is_feature_enabled_override(*args, **kwargs):
    return True

  async def _get_user_subscription_tier_override(*args, **kwargs):
    return 2, "Plus"

  monkeypatch.setattr("app.core.security.is_feature_enabled", _is_feature_enabled_override)
  monkeypatch.setattr("app.core.security.get_user_subscription_tier", _get_user_subscription_tier_override)

  user = MagicMock()
  user.status = UserStatus.APPROVED
  user.id = uuid.uuid4()
  claims = {"tier": "Plus"}

  widget_id = uuid.uuid4()
  original_content = b"<b>Hello World</b>"
  content_bytes = brotli.compress(original_content)

  mock_widget = MagicMock()
  mock_widget.fenster_id = widget_id
  mock_widget.type = FensterWidgetType.INLINE_BLOB
  mock_widget.content = content_bytes
  mock_widget.url = None

  # Mock DB execution
  mock_result = MagicMock()
  mock_result.scalar_one_or_none.return_value = mock_widget
  mock_db.execute.return_value = mock_result

  app.dependency_overrides[get_current_identity] = lambda: (user, claims)
  app.dependency_overrides[get_db] = lambda: mock_db

  try:
    response = client.get(f"/api/v1/fenster/{widget_id}")
    assert response.status_code == 200
    # TestClient decompresses content automatically
    assert response.content == original_content
    assert response.headers["content-encoding"] == "br"
    assert "text/html" in response.headers["content-type"]
    assert response.headers["content-security-policy"] == "frame-ancestors 'self'"
  finally:
    del app.dependency_overrides[get_current_identity]
    del app.dependency_overrides[get_db]


@pytest.mark.anyio
async def test_fenster_success_redirect(client, mock_db, monkeypatch):
  async def _is_feature_enabled_override(*args, **kwargs):
    return True

  async def _get_user_subscription_tier_override(*args, **kwargs):
    return 2, "Plus"

  monkeypatch.setattr("app.core.security.is_feature_enabled", _is_feature_enabled_override)
  monkeypatch.setattr("app.core.security.get_user_subscription_tier", _get_user_subscription_tier_override)

  user = MagicMock()
  user.status = UserStatus.APPROVED
  user.id = uuid.uuid4()
  claims = {"tier": "Plus"}

  widget_id = uuid.uuid4()
  target_url = "https://cdn.example.com/widget.html"

  mock_widget = MagicMock()
  mock_widget.fenster_id = widget_id
  mock_widget.type = FensterWidgetType.CDN_URL
  mock_widget.content = None
  mock_widget.url = target_url

  # Mock DB execution
  mock_result = MagicMock()
  mock_result.scalar_one_or_none.return_value = mock_widget
  mock_db.execute.return_value = mock_result

  app.dependency_overrides[get_current_identity] = lambda: (user, claims)
  app.dependency_overrides[get_db] = lambda: mock_db

  try:
    response = client.get(f"/api/v1/fenster/{widget_id}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == target_url
  finally:
    del app.dependency_overrides[get_current_identity]
    del app.dependency_overrides[get_db]
