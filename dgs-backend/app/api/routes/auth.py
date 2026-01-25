import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.firebase import build_rbac_claims, set_custom_claims, verify_id_token
from app.schema.sql import UserStatus
from app.services.rbac import get_role_by_id, get_role_by_name
from app.services.users import create_user, get_user_by_firebase_uid, resolve_auth_method

router = APIRouter()
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
  id_token: str = Field(..., alias="idToken")


class SignupRequest(BaseModel):
  id_token: str = Field(..., alias="idToken")
  full_name: str = Field(..., alias="fullName")
  email: str | None = None
  profession: str | None = None
  city: str | None = None
  country: str | None = None
  age: int | None = None
  photo_url: str | None = Field(None, alias="photoUrl")


@router.post("/login")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """
  Check if user exists and return status.
  """
  logger.info("Login request received")
  # Verify the Firebase token before any database access.
  try:
    decoded_token = await run_in_threadpool(verify_id_token, request.id_token)
  except Exception as e:
    logger.error("Login failed: Token verification crashed: %s", e, exc_info=True)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token") from e

  if not decoded_token:
    logger.warning("Login failed: Invalid ID token (empty result)")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token")

  # Extract identity details for downstream lookups.
  firebase_uid = decoded_token.get("uid")
  email = decoded_token.get("email")
  logger.debug("Token verified. UID: %s, Email: %s", firebase_uid, email)

  if not firebase_uid:
    logger.error("Login failed: Token missing uid")
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token missing uid")

  # Check if user exists in DB using ORM queries for safety and consistency.
  user = await get_user_by_firebase_uid(db, firebase_uid)

  if not user:
    logger.info("Login checked: User not registered. UID: %s", firebase_uid)
    return {"exists": False, "user": None}

  # Resolve role metadata for frontend display.
  role = await get_role_by_id(db, user.role_id)
  if role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="User role missing")

  logger.info("Login successful. User: %s", user.email)
  return {
    "exists": True,
    "user": {"email": user.email, "status": user.status, "full_name": user.full_name, "photo_url": user.photo_url, "role": {"id": str(role.id), "name": role.name, "level": role.level}, "org_id": str(user.org_id) if user.org_id else None},
  }


@router.post("/signup")
async def signup(request: SignupRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """
  Register a new user.
  """
  logger.info("Signup request received. Full Name: %s", request.full_name)
  # Verify the Firebase token before provisioning a user record.
  try:
    decoded_token = await run_in_threadpool(verify_id_token, request.id_token)
  except Exception as e:
    logger.error("Signup failed: Token verification crashed: %s", e, exc_info=True)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token") from e

  if not decoded_token:
    logger.warning("Signup failed: Invalid ID token")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token")

  # Extract identity and provider data from the token claims.
  firebase_uid = decoded_token.get("uid")
  token_email = decoded_token.get("email")
  provider_id = decoded_token.get("firebase", {}).get("sign_in_provider")
  logger.debug("Signup token verified. UID: %s, Email: %s, Provider: %s", firebase_uid, token_email, provider_id)

  if not firebase_uid or not token_email:
    logger.error("Signup failed: Token missing uid or email")
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token missing uid or email")

  # Check if user already exists using ORM queries for safety and consistency.
  existing_user = await get_user_by_firebase_uid(db, firebase_uid)

  if existing_user:
    logger.warning("Signup failed: User already registered. UID: %s", firebase_uid)
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already registered")

  # Resolve default role for new users to ensure RBAC consistency.
  default_role = await get_role_by_name(db, "Org Member")
  if default_role is None:
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Default role missing")

  # Create user
  try:
    user = await create_user(
      db,
      firebase_uid=firebase_uid,
      email=token_email,
      full_name=request.full_name,
      profession=request.profession,
      city=request.city,
      country=request.country,
      age=request.age,
      photo_url=request.photo_url,
      provider=provider_id,
      role_id=default_role.id,
      org_id=None,
      status=UserStatus.PENDING,
      auth_method=resolve_auth_method(provider_id),
    )
  except Exception as e:
    logger.error("Signup failed: Database error during creation for %s: %s", token_email, e, exc_info=True)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user") from e

  # Sync initial RBAC claims to Firebase for fast middleware checks.
  try:
    claims = build_rbac_claims(role_id=str(default_role.id), role_name=default_role.name, role_level=default_role.level, org_id=None, status=user.status)
    await run_in_threadpool(set_custom_claims, firebase_uid, claims)
  except Exception as e:
    logger.error("Signup failed: Unable to set custom claims for %s: %s", token_email, e, exc_info=True)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to sync user claims") from e

  logger.info("Signup successful. Created user: %s", user.email)
  return {"status": "success", "user": {"email": user.email, "status": user.status, "id": str(user.id), "role": {"id": str(default_role.id), "name": default_role.name, "level": default_role.level}, "org_id": None}}
