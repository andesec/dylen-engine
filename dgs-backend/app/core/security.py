from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from firebase_admin import auth
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.core.database import get_db
from app.schema.sql import User

settings = get_settings()


async def get_current_user(request: Request, session_cookie: Annotated[str | None, Cookie(alias="session")] = None, db: AsyncSession = Depends(get_db)) -> User:  # noqa: B008
  """
  Verifies the session cookie and retrieves the current user.
  """

  # Check for Dev Key bypass
  dev_key_header = request.headers.get("X-DGS-Dev-Key")
  if dev_key_header and dev_key_header == settings.dev_key:
    # Return a mock admin user or similar if dev key is present.
    # Ideally, we should have a dedicated service user or handle this carefully.
    # For now, let's look for a special admin user or create a temporary obj.
    # Or we can just bypass the check if the caller logic handles it, but this dependency is typed to return User.
    # Let's create a dummy user object for dev key access.
    return User(id=None, firebase_uid="dev-key-user", email="dev@local", is_approved=True)

  if not session_cookie:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

  try:
    decoded_claims = await run_in_threadpool(auth.verify_session_cookie, session_cookie, check_revoked=True)
    firebase_uid = decoded_claims.get("uid")
  except Exception:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from None

  stmt = select(User).where(User.firebase_uid == firebase_uid)
  result = await db.execute(stmt)
  user = result.scalar_one_or_none()

  if not user:
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

  return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:  # noqa: B008
  if not current_user.is_approved:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
  return current_user


async def get_current_admin_user(current_user: User = Depends(get_current_active_user)) -> User:  # noqa: B008
  if not current_user.is_admin:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
  return current_user
