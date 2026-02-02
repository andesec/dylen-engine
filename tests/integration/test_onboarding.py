import uuid
from unittest.mock import MagicMock, patch

import pytest
from app.schema.sql import User, UserStatus
from httpx import AsyncClient


# Mock verify_id_token
@pytest.fixture
def mock_verify_id_token():
  with patch("app.core.security.verify_id_token") as mock_verify:
    yield mock_verify


@pytest.fixture
def anyio_backend():
  return "asyncio"


@pytest.mark.anyio
async def test_get_my_profile_structure(async_client: AsyncClient, db_session, mock_verify_id_token):
  # Setup user
  uid = str(uuid.uuid4())
  user_id = uuid.uuid4()
  mock_verify_id_token.return_value = {"uid": uid, "email": "test@example.com"}

  user = User(id=user_id, firebase_uid=uid, email="test@example.com", status=UserStatus.PENDING, role_id=uuid.uuid4(), onboarding_completed=False)

  # DB mock for get_user_by_firebase_uid
  result_mock = MagicMock()
  result_mock.scalar_one_or_none.return_value = user
  db_session.execute.return_value = result_mock

  response = await async_client.get("/api/me", headers={"Authorization": "Bearer token"})

  assert response.status_code == 200
  data = response.json()
  assert data["id"] == str(user_id)
  assert data["email"] == "test@example.com"
  assert data["status"] == "PENDING"
  assert data["onboardingCompleted"] is False


@pytest.mark.anyio
async def test_complete_onboarding(async_client: AsyncClient, db_session, mock_verify_id_token):
  uid = str(uuid.uuid4())
  user_id = uuid.uuid4()
  mock_verify_id_token.return_value = {"uid": uid, "email": "test@example.com"}

  user = User(id=user_id, firebase_uid=uid, email="test@example.com", status=UserStatus.PENDING, role_id=uuid.uuid4(), onboarding_completed=False)

  # Mock DB find
  result_mock = MagicMock()
  result_mock.scalar_one_or_none.return_value = user
  db_session.execute.return_value = result_mock

  payload = {
    "basic": {"age": 25, "gender": "Male", "city": "Test City", "country": "Test Country", "occupation": "Developer"},
    "personalization": {"topics_of_interest": ["Coding", "AI"], "intended_use": "Learning"},
    "legal": {"accepted_terms": True, "accepted_privacy": True, "terms_version": "1.0", "privacy_version": "1.0"},
  }

  response = await async_client.post("/api/onboarding/complete", json=payload, headers={"Authorization": "Bearer token"})

  assert response.status_code == 200
  data = response.json()
  assert data["onboardingCompleted"] is True
  assert data["status"] == "PENDING"  # It remains PENDING in spec, until admin approves? Spec: "User becomes PENDING". It was PENDING, so it stays PENDING or moves from something else? Spec says "onboarding_completed = true, status = PENDING".

  # Verify user object update
  assert user.onboarding_completed is True
  assert user.age == 25
  assert user.occupation == "Developer"
  assert user.topics_of_interest == ["Coding", "AI"]
  assert user.accepted_terms_at is not None


@pytest.mark.anyio
async def test_onboarding_idempotency(async_client: AsyncClient, db_session, mock_verify_id_token):
  uid = str(uuid.uuid4())
  user_id = uuid.uuid4()
  mock_verify_id_token.return_value = {"uid": uid, "email": "test@example.com"}

  user = User(
    id=user_id,
    firebase_uid=uid,
    email="test@example.com",
    status=UserStatus.PENDING,
    role_id=uuid.uuid4(),
    onboarding_completed=True,  # Already completed
  )

  result_mock = MagicMock()
  result_mock.scalar_one_or_none.return_value = user
  db_session.execute.return_value = result_mock

  payload = {
    "basic": {"age": 25, "gender": "Male", "city": "New City", "country": "New Country", "occupation": "New Job"},
    "personalization": {"topics_of_interest": ["New"], "intended_use": "New"},
    "legal": {"accepted_terms": True, "accepted_privacy": True, "terms_version": "2.0", "privacy_version": "2.0"},
  }

  response = await async_client.post("/api/onboarding/complete", json=payload, headers={"Authorization": "Bearer token"})

  assert response.status_code == 200

  # Should NOT update fields if already completed
  # The endpoint implementation returns current state.
  # It does NOT update user object in DB.
  # How to verify? I can check if DB.add was called or if user fields changed.
  # In this mock setup, user is a python object. If code modified it, it would change.

  # Wait, my implementation checks `if current_user.onboarding_completed: return ...`.
  # It does NOT touch `current_user` fields.

  # But wait, `user` object passed to `scalar_one_or_none` is the same reference returned?
  # Yes.

  assert user.city != "New City"  # Should be whatever it was (None or default)
  # user initialized with None/defaults for fields not passed to constructor.
  # User model has defaults?
  # `city` is nullable.

  assert user.city is None  # Assuming it was None initially


@pytest.mark.anyio
async def test_onboarding_validation_failure(async_client: AsyncClient, db_session, mock_verify_id_token):
  uid = str(uuid.uuid4())
  mock_verify_id_token.return_value = {"uid": uid, "email": "test@example.com"}

  # We need a user to pass auth, even if validation fails later
  user = User(id=uuid.uuid4(), firebase_uid=uid, email="test@example.com", status=UserStatus.PENDING, role_id=uuid.uuid4(), onboarding_completed=False)
  result_mock = MagicMock()
  result_mock.scalar_one_or_none.return_value = user
  db_session.execute.return_value = result_mock

  payload = {
    "basic": {
      "age": 10,  # Invalid age < 13
      "gender": "Male",
      "city": "Test City",
      "country": "Test Country",
      "occupation": "Developer",
    },
    "personalization": {"topics_of_interest": ["Coding"], "intended_use": "Learning"},
    "legal": {"accepted_terms": True, "accepted_privacy": True, "terms_version": "1.0", "privacy_version": "1.0"},
  }

  response = await async_client.post("/api/onboarding/complete", json=payload, headers={"Authorization": "Bearer token"})
  assert response.status_code == 422  # Validation Error
