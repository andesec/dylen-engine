import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db
from app.core.firebase import verify_id_token
from app.schema.sql import User

router = APIRouter()


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
async def login(request: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """
  Exchange Firebase ID Token for a Session Cookie.
  """
  decoded_token = await run_in_threadpool(verify_id_token, request.id_token)
  if not decoded_token:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token")

  firebase_uid = decoded_token.get("uid")
  
  if not firebase_uid:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token missing uid")

  # Check if user exists in DB
  stmt = select(User).where(User.firebase_uid == firebase_uid)
  result = await db.execute(stmt)
  user = result.scalar_one_or_none()

  if not user:
    # Auto-signup is disabled. Frontend should redirect to signup.
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not registered")

  return await _create_session(response, request.id_token, user)


@router.post("/signup")
async def signup(request: SignupRequest, response: Response, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """
  Register a new user.
  """
  decoded_token = await run_in_threadpool(verify_id_token, request.id_token)
  if not decoded_token:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token")
  
  firebase_uid = decoded_token.get("uid")
  token_email = decoded_token.get("email")

  if not firebase_uid or not token_email:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token missing uid or email")

  # Check if user already exists
  stmt = select(User).where(User.firebase_uid == firebase_uid)
  result = await db.execute(stmt)
  existing_user = result.scalar_one_or_none()

  if existing_user:
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already registered")

  # Create user
  user = User(
    firebase_uid=firebase_uid,
    email=token_email, # Trust token email over request email
    full_name=request.full_name,
    profession=request.profession,
    city=request.city,
    country=request.country,
    age=request.age,
    photo_url=request.photo_url,
    is_approved=False
  )
  db.add(user)
  await db.commit()
  await db.refresh(user)

  return await _create_session(response, request.id_token, user)


async def _create_session(response: Response, id_token: str, user: User) -> dict[str, Any]:
  # Create session cookie
  # We use the Firebase Admin SDK to create a secure session cookie.
  # This allows us to set a longer expiration (5 days) compared to the short-lived ID token.
  try:
    # Create a session cookie using Firebase Admin SDK
    # Expiration time: 5 days
    from firebase_admin import auth

    expires_in = datetime.timedelta(days=5)
    session_cookie = await run_in_threadpool(auth.create_session_cookie, id_token, expires_in=expires_in)

    response.set_cookie(key="session", value=session_cookie, httponly=True, secure=True, samesite="lax", max_age=int(expires_in.total_seconds()))
    return {"status": "success", "user": {"email": user.email, "is_approved": user.is_approved}}
  except Exception:
    # Fallback or error handling
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Failed to create session cookie") from None
