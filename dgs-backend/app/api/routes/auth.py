import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.firebase import verify_id_token
from app.services.users import create_user, ensure_usage_row, get_user_by_firebase_uid

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
  try:
    decoded_token = await run_in_threadpool(verify_id_token, request.id_token)
  except Exception as e:
    logger.error("Login failed: Token verification crashed: %s", e, exc_info=True)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token") from e

  if not decoded_token:
    logger.warning("Login failed: Invalid ID token (empty result)")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token")

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

  logger.info("Login successful. User: %s", user.email)
  return {"exists": True, "user": {"email": user.email, "is_approved": user.is_approved, "full_name": user.full_name, "photo_url": user.photo_url}}


@router.post("/signup")
async def signup(request: SignupRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """
  Register a new user.
  """
  logger.info("Signup request received. Full Name: %s", request.full_name)
  try:
    decoded_token = await run_in_threadpool(verify_id_token, request.id_token)
  except Exception as e:
    logger.error("Signup failed: Token verification crashed: %s", e, exc_info=True)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token") from e

  if not decoded_token:
    logger.warning("Signup failed: Invalid ID token")
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token")

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

  # Create user
  try:
    user = await create_user(
      db, firebase_uid=firebase_uid, email=token_email, full_name=request.full_name, profession=request.profession, city=request.city, country=request.country, age=request.age, photo_url=request.photo_url, provider=provider_id, is_approved=False
    )
  except Exception as e:
    logger.error("Signup failed: Database error during creation for %s: %s", token_email, e, exc_info=True)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user") from e

  await ensure_usage_row(db, user)
  logger.info("Signup successful. Created user: %s", user.email)
  return {"status": "success", "user": {"email": user.email, "is_approved": user.is_approved, "id": str(user.id)}}
