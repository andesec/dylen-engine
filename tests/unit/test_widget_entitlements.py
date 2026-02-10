"""Unit tests for widget entitlement validation."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.main import app
from app.schema.sql import User, UserStatus
from app.services.widget_entitlements import validate_widget_entitlements
from fastapi import HTTPException
from fastapi.testclient import TestClient


def _payload_with_fenster() -> dict[str, object]:
  """Build a valid lesson payload that requests the fenster widget."""
  return {
    "topic": "How are soaps made?",
    "details": "Describe the process and method in detail",
    "primary_language": "English",
    "learner_level": "newbie",
    "depth": "highlights",
    "blueprint": "knowledgeunderstanding",
    "teaching_style": ["conceptual"],
    "widgets": ["fenster", "mcqs", "fillblank"],
    "idempotency_key": "",
  }


def _override_auth_and_db() -> None:
  """Install auth and DB overrides for route-level validation tests."""
  user = User(id=uuid.uuid4(), firebase_uid="uid-test", email="ok@example.com", role_id=uuid.uuid4(), status=UserStatus.APPROVED)
  app.dependency_overrides[get_current_active_user] = lambda: user

  async def _db_override():
    yield object()

  app.dependency_overrides[get_db] = _db_override


def test_validate_widget_entitlements_blocks_fenster_when_tier_none() -> None:
  """Reject fenster widget selection for tiers without fenster access."""
  with pytest.raises(HTTPException) as exc_info:
    validate_widget_entitlements(["fenster", "mcqs", "fillblank"], runtime_config={"fenster.widgets_tier": "none"})
  assert exc_info.value.status_code == 403
  detail = exc_info.value.detail
  assert detail["error"] == "UPGRADE_REQUIRED"
  assert detail["feature"] == "widget"
  assert detail["widgets"] == ["fenster"]
  assert detail["min_tier"] == "flash"


def test_validate_widget_entitlements_allows_fenster_when_tier_flash() -> None:
  """Allow fenster widget selection when the runtime tier grants access."""
  validate_widget_entitlements(["fenster", "mcqs", "fillblank"], runtime_config={"fenster.widgets_tier": "flash"})


@pytest.mark.parametrize("path", ["/v1/lessons/outcomes", "/v1/lessons/generate", "/v1/lessons/jobs"])
def test_lesson_routes_block_fenster_widgets_for_ineligible_tiers(monkeypatch, path: str) -> None:
  """Return 403 when a request selects fenster without required tier entitlement."""
  _override_auth_and_db()
  # Keep route execution focused on entitlement validation.
  monkeypatch.setattr("app.api.routes.lessons.check_concurrency_limit", AsyncMock(return_value=None))
  monkeypatch.setattr("app.api.routes.lessons.get_user_subscription_tier", AsyncMock(return_value=(1, "Free")))
  monkeypatch.setattr(
    "app.api.routes.lessons.resolve_effective_runtime_config", AsyncMock(return_value={"fenster.widgets_tier": "none", "limits.max_topic_length": 200, "limits.lessons_per_week": 10, "limits.sections_per_month": 100, "limits.outcomes_checks_per_week": 10})
  )
  client = TestClient(app)
  try:
    response = client.post(path, json=_payload_with_fenster())
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "UPGRADE_REQUIRED"
    assert response.json()["detail"]["widgets"] == ["fenster"]
  finally:
    app.dependency_overrides.clear()
