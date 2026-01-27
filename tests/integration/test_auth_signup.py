import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from app.schema.quotas import SubscriptionTier
from app.schema.sql import Role, RoleLevel, User, UserStatus


# Mock Firebase verify_id_token
@pytest.fixture
def mock_verify_id_token():
  with patch("app.api.routes.auth.verify_id_token") as mock_auth, patch("app.core.security.verify_id_token") as mock_security:
    # Link them so setting return_value on the yielded mock affects both
    mock_security.return_value = mock_auth.return_value
    yield mock_auth  # Yield one, but both are active
    # Note: If tests set .return_value on the yielded mock, we need to ensure it propagates or we just set it on both if needed.
    # Actually, simpler to just yield mock_auth, and in the tests we set mock_auth.return_value.
    # But mock_security needs to return the same.
    # We can use side_effect to delegate?
    # Or just keep it simple:
    mock_security.side_effect = lambda *args, **kwargs: mock_auth(*args, **kwargs)


@pytest.fixture
def anyio_backend():
  return "asyncio"


@pytest.fixture
def mock_firebase_admin_auth():
  # Patch set_custom_claims where it is USED in the route handler
  with patch("app.api.routes.auth.set_custom_claims") as mock_set_claims:
    with patch("firebase_admin.auth") as mock_admin, patch("app.core.security.auth") as mock_security:
      # Configure both mocks to behave similarly
      mock_admin.create_session_cookie.return_value = "mock_session_cookie"
      mock_security.create_session_cookie.return_value = "mock_session_cookie"

      # Return mock_security because that's what verify_session_cookie uses
      # But create_session_cookie uses mock_admin (runtime import)
      # Simpler: Make them the SAME mock object
      mock_security.side_effect = mock_admin.side_effect
      mock_security.return_value = mock_admin.return_value
      mock_security.verify_session_cookie = mock_admin.verify_session_cookie
      mock_security.create_session_cookie = mock_admin.create_session_cookie

      yield mock_admin


@pytest.mark.anyio
async def test_login_user_not_found(async_client: AsyncClient, mock_verify_id_token):
  mock_verify_id_token.return_value = {"uid": "new_user_123", "email": "new@example.com", "name": "New User"}

  response = await async_client.post("/api/auth/login", json={"idToken": "valid_token"})

  assert response.status_code == 200
  assert response.json() == {"exists": False, "user": None}


@pytest.mark.anyio
async def test_signup_flow(async_client: AsyncClient, db_session, mock_verify_id_token, mock_firebase_admin_auth):
  mock_verify_id_token.return_value = {"uid": "signup_user_123", "email": "signup@example.com", "name": "Signup User"}

  # 1. Signup
  signup_payload = {"idToken": "valid_token", "fullName": "Signup User", "email": "signup@example.com", "profession": "Developer", "city": "Test City", "country": "Test Country", "age": 25, "photoUrl": "http://example.com/photo.jpg"}

  # Setup DB mock
  # Must handle:
  # 1. check for existing user (returns None)
  # 2. check for 'Org Member' role (returns Role object)
  # 3. check for 'Free' tier (returns Tier object)
  mock_role = Role(id=uuid.uuid4(), name="Org Member", level=RoleLevel.TENANT)
  free_tier = SubscriptionTier(id=1, name="Free", max_file_upload_kb=1024)

  result_mock = MagicMock()
  # Use side_effect to return different values for sequential calls:
  # Call 1: User lookup -> None (User not found)
  # Call 2: Role lookup -> mock_role
  # Call 3: Tier lookup -> free_tier
  result_mock.scalar_one_or_none.side_effect = [None, mock_role, free_tier]
  db_session.execute.return_value = result_mock

  response = await async_client.post("/api/auth/signup", json=signup_payload)

  assert response.status_code == 200
  data = response.json()
  assert data["status"] == "success"
  assert data["user"]["email"] == "signup@example.com"
  assert data["user"]["status"] == UserStatus.PENDING
  assert "role" in data["user"]
  assert data["user"]["role"]["name"] == "Org Member"

  # Verify User data returned
  assert "user" in data
  assert "email" in data["user"]

  # Verify DB interactions
  # Verify add was called
  assert db_session.add.called
  added_user = db_session.add.call_args[0][0]
  assert isinstance(added_user, User)
  assert added_user.firebase_uid == "signup_user_123"
  assert added_user.email == "signup@example.com"
  assert added_user.profession == "Developer"
  assert added_user.city == "Test City"
  assert added_user.country == "Test Country"
  assert added_user.age == 25
  assert added_user.photo_url == "http://example.com/photo.jpg"
  assert added_user.status == UserStatus.PENDING

  # 2. Login after signup (should succeed and return user)
  # Now unapproved users CAN login

  # Update mock to return the user we just "added"
  # Login checks: 1. User lookup, 2. Role lookup
  result_mock.scalar_one_or_none.side_effect = None
  # Side effect for Login: [User, Role]
  result_mock.scalar_one_or_none.side_effect = [added_user, mock_role]
  db_session.execute.return_value = result_mock

  response_login = await async_client.post("/api/auth/login", json={"idToken": "valid_token"})
  assert response_login.status_code == 200
  assert response_login.json()["user"]["status"] == UserStatus.PENDING
  assert response_login.json()["user"]["role"]["name"] == "Org Member"


@pytest.mark.anyio
async def test_get_profile(async_client: AsyncClient, db_session, mock_verify_id_token, mock_firebase_admin_auth):
  mock_verify_id_token.return_value = {"uid": "profile_user_123", "email": "profile@example.com", "name": "Profile User"}

  # Setup DB mock for Signup

  mock_role = Role(id=uuid.uuid4(), name="Org Member", level=RoleLevel.TENANT)

  free_tier = SubscriptionTier(id=1, name="Free", max_file_upload_kb=1024)

  result_mock = MagicMock()

  # Call 1: User lookup -> None

  # Call 2: Role lookup -> mock_role

  # Call 3: Tier lookup -> free_tier

  result_mock.scalar_one_or_none.side_effect = [None, mock_role, free_tier]

  db_session.execute.return_value = result_mock

  # 1. Signup

  response = await async_client.post("/api/auth/signup", json={"idToken": "token", "fullName": "Profile User", "email": "profile@example.com"})

  assert response.status_code == 200

  # Setup DB mock for subsequent Login/Get calls

  user = User(id=uuid.uuid4(), firebase_uid="profile_user_123", email="profile@example.com", full_name="Profile User", status=UserStatus.PENDING, role_id=mock_role.id)

  # Reset side effect and return user

  result_mock.scalar_one_or_none.side_effect = None

  # Sequence for Login: [User, Role]

  # Sequence for Get Me (PENDING): [User] (fails at dependency, no role lookup?)

  # Actually, get_current_active_user calls get_current_identity (User lookup) -> checks status -> raises 403.

  # So DB calls: Login (2), Get Me (1 - User only).

  # Sequence for Get Me (APPROVED): [User, Role]

  result_mock.scalar_one_or_none.side_effect = [user, mock_role, user, user, mock_role]

  db_session.execute.return_value = result_mock

  # 2. Login to get cookie

  login_resp = await async_client.post("/api/auth/login", json={"idToken": "token"})

  assert login_resp.status_code == 200

  # 3. Get Me (PENDING) -> Should be 403

  response = await async_client.get("/api/user/me", headers={"Authorization": "Bearer token"})

  assert response.status_code == 403

  # 4. Approve

  user.status = UserStatus.APPROVED

  # 5. Get Me (APPROVED) -> Should be 200

  response = await async_client.get("/api/user/me", headers={"Authorization": "Bearer token"})

  assert response.status_code == 200

  data = response.json()

  assert data["status"] == UserStatus.APPROVED

  assert data["role"]["name"] == "Org Member"
