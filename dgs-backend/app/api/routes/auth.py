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


@router.post("/login")
async def login(request: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
  """
  Exchange Firebase ID Token for a Session Cookie.
  """
  decoded_token = await run_in_threadpool(verify_id_token, request.id_token)
  if not decoded_token:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid ID token")

  firebase_uid = decoded_token.get("uid")
  email = decoded_token.get("email")

  if not firebase_uid or not email:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token missing uid or email")

  # Check if user exists in DB
  stmt = select(User).where(User.firebase_uid == firebase_uid)
  result = await db.execute(stmt)
  user = result.scalar_one_or_none()

  if not user:
    # Create user if not exists (auto-signup)
    # Note: is_approved is False by default
    user = User(firebase_uid=firebase_uid, email=email, full_name=decoded_token.get("name"), is_approved=False)
    db.add(user)
    await db.commit()
    await db.refresh(user)

  # Check approval
  if not user.is_approved:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is not approved by admin.")

  # Create session cookie
  # For simplicity, we are using the ID token as the session cookie value or creating a custom session token.
  # The requirement says: "DGS verifies the ID Token ... DGS generates a session cookie (or an encrypted internal JWT)"
  # Since implementing a full JWT issuer is complex, we can use the firebase_uid signed, or just the ID token if it is long lived enough (it is 1h).
  # However, Firebase ID tokens are short lived (1 hour). Session cookies are better.
  # Firebase Admin SDK can create session cookies.

  try:
    # Create a session cookie using Firebase Admin SDK
    # Expiration time: 5 days
    from firebase_admin import auth

    expires_in = datetime.timedelta(days=5)
    session_cookie = await run_in_threadpool(auth.create_session_cookie, request.id_token, expires_in=expires_in)

    response.set_cookie(key="session", value=session_cookie, httponly=True, secure=True, samesite="lax", max_age=int(expires_in.total_seconds()))
    return {"status": "success", "user": {"email": user.email, "is_approved": user.is_approved}}
  except Exception:
    # Fallback or error handling
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Failed to create session cookie") from None
