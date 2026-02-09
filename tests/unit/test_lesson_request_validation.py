"""Unit tests for lesson request validation rules."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from app.api.models import GenerateLessonRequest
from app.core.database import get_db
from app.core.security import get_current_active_user
from app.main import app
from app.schema.sql import User, UserStatus
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError


def _valid_payload() -> dict[str, object]:
  """Build a valid lesson request payload used by model and route tests."""
  # Keep a single canonical payload so field validation differences are easy to reason about.
  return {
    "topic": "How are soaps made?",
    "details": "Describe the process and method in detail",
    "primary_language": "English",
    "learner_level": "newbie",
    "depth": "highlights",
    "blueprint": "knowledgeunderstanding",
    "teaching_style": ["conceptual"],
    "widgets": ["markdown", "mcqs", "fillblank"],
    "idempotency_key": "",
  }


def _override_auth() -> None:
  """Install auth and DB overrides needed for request-validation route tests."""
  # Provide a valid active user so tests can focus on request-body validation behavior.
  user = User(id=uuid.uuid4(), firebase_uid="uid-test", email="ok@example.com", role_id=uuid.uuid4(), status=UserStatus.APPROVED)
  app.dependency_overrides[get_current_active_user] = lambda: user

  # Provide a no-op DB dependency because invalid requests should fail before DB access.
  async def _db_override():
    yield object()

  app.dependency_overrides[get_db] = _db_override


def test_generate_lesson_request_accepts_required_fields() -> None:
  """Accept required blueprint/style inputs and unique valid widgets."""
  payload = _valid_payload()
  payload["teaching_style"] = ["conceptual", "theoretical", "practical"]
  payload["widgets"] = ["markdown", "mcqs", "fillblank", "stepFlow"]
  request = GenerateLessonRequest.model_validate(payload)
  assert request.blueprint == "knowledgeunderstanding"
  assert request.teaching_style == ["conceptual", "theoretical", "practical"]
  assert request.widgets == ["markdown", "mcqs", "fillblank", "stepFlow"]


@pytest.mark.parametrize(
  ("mutator", "expected_message"),
  [
    (lambda payload: payload.pop("blueprint"), "Field required"),
    (lambda payload: payload.pop("teaching_style"), "Field required"),
    (lambda payload: payload.update({"teaching_style": []}), "at least 1 item"),
    (lambda payload: payload.update({"teaching_style": ["conceptual", "conceptual"]}), "Teaching style entries must be unique"),
    (lambda payload: payload.update({"widgets": ["markdown", "markdown", "mcqs"]}), "Widget entries must be unique"),
    (lambda payload: payload.update({"widgets": ["ul", "mcqs", "fillblank"]}), "Unsupported widget id"),
    (lambda payload: payload.update({"widgets": ["markdown", "mcqs"]}), "at least 3 items"),
    (lambda payload: payload.update({"widgets": ["markdown", "mcqs", "fillblank", "stepflow", "tr", "table", "compare", "flip"]}), "at most 7 items"),
  ],
)
def test_generate_lesson_request_rejects_invalid_values(mutator, expected_message: str) -> None:
  """Reject invalid blueprint/style/widget combinations before route execution."""
  payload = _valid_payload()
  mutator(payload)
  with pytest.raises(ValidationError) as exc_info:
    GenerateLessonRequest.model_validate(payload)
  assert expected_message in str(exc_info.value)


@pytest.mark.parametrize("path", ["/v1/lessons/outcomes", "/v1/lessons/generate", "/v1/lessons/jobs"])
@pytest.mark.parametrize(("field", "value"), [("blueprint", "not-a-blueprint"), ("teaching_style", ["conceptual", "conceptual"]), ("widgets", ["markdown", "markdown", "mcqs"])])
def test_lesson_routes_reject_invalid_blueprint_style_widgets(path: str, field: str, value: object) -> None:
  """Return 422 for invalid request values across all lesson write endpoints."""
  _override_auth()
  client = TestClient(app)
  try:
    payload = _valid_payload()
    payload[field] = value
    response = client.post(path, json=payload)
    assert response.status_code == 422
  finally:
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
  ("path", "patch_target"), [("/v1/lessons/outcomes", "app.api.routes.lessons.check_concurrency_limit"), ("/v1/lessons/generate", "app.api.routes.lessons.check_concurrency_limit"), ("/v1/lessons/jobs", "app.api.routes.lessons.get_user_subscription_tier")]
)
def test_lesson_routes_accept_valid_payload_at_request_boundary(monkeypatch, path: str, patch_target: str) -> None:
  """Ensure valid payloads pass request validation and reach route-level logic."""
  _override_auth()
  # Raise a controlled HTTP error inside route logic to prove request parsing already succeeded.
  monkeypatch.setattr(patch_target, AsyncMock(side_effect=HTTPException(status_code=429, detail="controlled-route-check")))
  client = TestClient(app)
  try:
    response = client.post(path, json=_valid_payload())
    assert response.status_code == 429
    assert response.json()["detail"] == "controlled-route-check"
  finally:
    app.dependency_overrides.clear()
